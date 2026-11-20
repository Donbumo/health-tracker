"""Fictitious exchange fixtures and isolated official draft preparation."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import DailyNutrition, FoodProduct, MealLog, NutritionImportDraft, NutritionImportReceipt, UploadedFile, User
from app.services import nutrition_import as imports, nutrition_import_review as compact
from app.services.importers.nutrition_exchange import common, intake, normalize, preparation, projection
from app.services.nutrition_math import NUTRIENTS, NutritionError
from tests.conftest import login
from tests.test_nutrition_import_source_21 import app  # Guarded SQLite/MariaDB 0046 fixture.


FIXTURES = Path(__file__).resolve().parents[2] / "examples" / "qa" / "nutrition-exchange"


def read(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def bytes_of(doc):
    return json.dumps(doc, ensure_ascii=False).encode()


def batch(doc):
    parsed = intake.parse(bytes_of(doc))
    return parsed.batch if parsed.batch is not None else common.adapt(parsed.document)


def analyze(doc, **kwargs):
    return normalize.evaluate(batch(doc), **kwargs)


def codes(record):
    return {diagnostic.code for diagnostic in record.diagnostics}


def document(food):
    return {
        "format": "health-tracker-nutrition", "version": "1.0", "date": "2030-02-18",
        "destination": "consumed", "meals": [{"type": "lunch", "foods": [food]}],
    }


def food(quantity=None, basis=None):
    return {
        "name": "Bocado ficticio QA",
        "quantity": quantity or {"amount": 100, "unit": "g"},
        "nutrition": {
            "basis": basis or {"kind": "consumed"},
            "values": {"energy": {"value": 50, "unit": "kcal"}},
        },
    }


def setup_qa(app):
    app.config.update(NUTRITION_INTELLIGENCE_ENABLED=True, NUTRITION_EXCHANGE_QA_ENABLED=True)


def upload(client, payload):
    return client.post(
        "/nutrition/import", data={"file": (BytesIO(payload), "QA-ficticia.json")},
        headers={"Accept": "application/json"},
    )


def row_for(user, response):
    assert response.status_code == 302, response.text
    return imports.owned(user, response.location.rsplit("/", 1)[-1])


def test_explicit_fixture_preserves_exact_sparse_vectors_and_decimal_totals():
    result = analyze(read("valid-explicit.json"))
    breakfast, lunch, dinner, snack = result.records
    assert set(breakfast.values) == set(NUTRIENTS)
    assert breakfast.values["zinc"].quality == "estimated"
    assert breakfast.values["sugar"].value == 0
    assert lunch.values["vitamin_d"].state == "trace"
    assert Decimal(lunch.contributions["sodium"]["limit"]) == Decimal("0.625")
    assert "chromium" not in lunch.values
    assert len(lunch.food.nutrition.additional) == 1
    assert "unsupported_nutrient" in codes(lunch)
    assert dinner.values["protein"].state == "unknown"
    assert "fiber" not in dinner.values
    assert "fiber" not in dinner.contributions
    assert snack.values["fiber"].value == 0
    energies = [Decimal(row.contributions["energy"]["value"]) for row in result.records]
    assert energies == list(map(Decimal, ("195", "150", "165.125", "60")))
    assert sum(energies) == Decimal("570.125")


def test_partial_keeps_source_values_and_reports_only_real_problems():
    result = analyze(read("valid-needs-review.json"))
    assert codes(result) == {"missing_destination"}
    no_basis, cross_unit, no_quantity, dish = result.records
    assert no_basis.values["energy"].value == 85 and no_basis.contributions is None
    assert codes(no_basis) == {"missing_basis"}
    assert no_basis.diagnostics[0].path == "/meals/0/foods/0/nutrition"
    assert codes(cross_unit) == {"incompatible_units"}
    assert codes(no_quantity) == {"missing_quantity"}
    assert codes(dish) == {"conflicting_authority"}
    assert dish.contributions is None
    assert dish.values["energy"].value == 120
    assert [child.nutrition.values["energy"].value for child in dish.food.ingredients] == [40, 70]
    consumed = analyze(read("valid-needs-review.json"), destination="consumed")
    assert "missing_date" in codes(consumed.records[0])
    assert "missing_date" not in codes(consumed.records[3])


@pytest.mark.parametrize(("unit", "reference", "l1", "l2", "expected"), [
    ("piece", "piece", "u\u0301nica ", " única", None),
    ("portion", "portion", "ración", "ración", None),
    ("piece", "portion", "rebanada", "rebanada", "missing_equivalence"),
    ("piece", "g", "rebanada", None, "missing_equivalence"),
    ("ml", "g", None, None, "incompatible_units"),
    ("portion", "portion", "taza pequeña", "taza grande", "missing_equivalence"),
])
def test_only_same_normalized_nominal_identity_scales(unit, reference, l1, l2, expected):
    quantity = {"amount": 2, "unit": unit, **({"label": l1} if l1 else {})}
    basis = {"amount": 1, "unit": reference, **({"label": l2} if l2 else {})}
    record, = analyze(document(food(quantity, basis))).records
    assert codes(record) == ({expected} if expected else set())
    if expected:
        assert record.contributions is None and record.values["energy"].value == 50
    else:
        assert Decimal(record.contributions["energy"]["value"]) == 100


@pytest.mark.parametrize("changed_field", ["quantity", "label", "basis", "different_entry"])
def test_equivalence_depends_on_the_exact_source_row(changed_field):
    doc = document(food({"amount": 2, "unit": "piece", "label": "pieza ficticia"},
                        {"amount": 100, "unit": "g"}))
    source = batch(doc)
    original = source.meals[0].foods[0]
    choice = normalize.FoodDecision(original, equivalence=normalize.Equivalence(Decimal(30), "Pesaje ficticio"))
    resolved, = normalize.evaluate(source, decisions={original.path: choice}).records
    assert Decimal(resolved.contributions["energy"]["value"]) == 30
    assert resolved.quantity.unit == "g" and resolved.food.quantity.unit == "piece"

    if changed_field == "quantity":
        candidate = replace(original, quantity=replace(original.quantity, amount=Decimal(3)))
    elif changed_field == "label":
        candidate = replace(original, quantity=replace(original.quantity, label="otra pieza"))
    elif changed_field == "basis":
        candidate = replace(original, nutrition=replace(
            original.nutrition, basis=replace(original.nutrition.basis, amount=Decimal(200))))
    else:
        candidate = replace(original, path=original.path.replace("foods/0", "foods/1"))
    new_source = replace(source, meals=(replace(source.meals[0], foods=(candidate,)),))
    review, = normalize.evaluate(new_source, decisions={candidate.path: choice}).records
    assert "stale_revision" in codes(review)
    assert review.contributions is None


def test_ingredients_sum_before_the_existing_snapshot_precision_boundary():
    child = food({"amount": 1, "unit": "g"}, {"amount": 3, "unit": "g"})
    child["nutrition"]["values"]["energy"]["value"] = 1
    dish = {"name": "Plato ficticio", "quantity": {"amount": 3, "unit": "g"}, "ingredients": [deepcopy(child) for _ in range(3)]}
    row, = analyze(document(dish)).records
    assert row.authority == "ingredients"
    assert Decimal(row.contributions["energy"]["value"]) == 1
    dish["quantity"]["amount"] = 4
    row, = analyze(document(dish)).records
    assert codes(row) == {"unverified_composition"}
    assert row.contributions is None


def spanish():
    return {
        "destino": "consumido", "fecha": "2030-02-18",
        "comidas": [{"tipo": "almuerzo", "alimentos": [{
            "nombre": "Bocado ficticio QA",
            "cantidad": {"valor": "0.15", "unidad": "kg"},
            "nutrición": {
                "base": {"cantidad": 100, "unidad": "g"},
                "valores": {"energía": {"valor": 130, "unidad": "kcal"},
                            "sodio": {"valor": "0.12", "unidad": "g", "calidad": "estimado"}},
            },
        }]}],
    }


def test_common_spanish_alias_and_flat_english_preserve_units_and_path():
    row, = analyze(spanish()).records
    assert row.quantity.amount == 150
    assert row.quantity.evidence.raw == {"valor": "0.15", "unidad": "kg"}
    assert row.quantity.evidence.conversion == "kg->g"
    sodium = row.values["sodium"]
    assert sodium.value == 120 and sodium.quality == "estimated"
    assert sodium.evidence.path == "/comidas/0/alimentos/0/nutrición/valores/sodio"
    assert sodium.evidence.raw == {"valor": "0.12", "unidad": "g", "calidad": "estimado"}
    assert Decimal(row.contributions["sodium"]["value"]) == 180
    en = {"date": "2030-02-18", "type": "lunch", "destination": "consumed", "foods": [food()]}
    row, = analyze(en).records
    assert row.food.path == "/foods/0"
    assert row.contributions["energy"]["value"] == "50"


@pytest.mark.parametrize("case", ["field", "vector", "boolean", "basis", "total_net"])
def test_common_conflicting_aliases_never_authorize_assumptions(case):
    doc = spanish()
    raw = doc["comidas"][0]["alimentos"][0]
    if case == "field":
        raw["name"] = "Otro ficticio"
        expected = "alias_conflict"
    elif case == "vector":
        raw["nutrición"]["valores"]["energy"] = {"value": 131, "unit": "kcal"}
        expected = "alias_conflict"
    elif case == "boolean":
        raw["cantidad"].update(amount=1, valor=True)
        expected = "alias_conflict"
    elif case == "basis":
        raw["nutrición"]["base"]["kind"] = "texto libre"
        expected = "basis_conflict"
    else:
        raw["nutrición"]["valores"]["carbohidratos"] = {"valor": 2, "unidad": "g"}
        expected = "ambiguous_nutrient"
    row, = analyze(doc).records
    assert expected in codes(row)
    assert row.contributions is None


def test_duplicate_candidates_are_never_discarded_or_resolved_by_basis_choice():
    doc = document(food())
    second = deepcopy(doc["meals"][0])
    doc["meals"].append(second)
    source = batch(doc)
    decision = normalize.FoodDecision(source.meals[0].foods[0], authority="dish")
    interpreted = normalize.evaluate(source, decisions={decision.original.path: decision},
                                    aggregate_dates={date(2030, 2, 18)})
    assert len(interpreted.records) == 2
    assert all(codes(row) == {"possible_duplicate", "day_overlap"} for row in interpreted.records)


def test_one_incompatible_basis_does_not_change_the_other_seventeen():
    doc = document(food())
    foods = doc["meals"][0]["foods"]
    foods[:] = [dict(food(), name=f"Alimento ficticio {i + 1}") for i in range(18)]
    foods[-1]["nutrition"]["basis"] = {"amount": 100, "unit": "ml"}
    rows = analyze(doc).records
    assert all(not row.diagnostics and row.contributions for row in rows[:17])
    assert codes(rows[-1]) == {"incompatible_units"}
    assert rows[-1].values["energy"].value == 50 and rows[-1].contributions is None


def test_exchange_opt_in_requires_testing_and_preserves_zero_writes_on_invalid_input(app, client, user):
    app.config.update(TESTING=False, NUTRITION_INTELLIGENCE_ENABLED=True, NUTRITION_EXCHANGE_QA_ENABLED=True)
    login(client)
    payload = bytes_of(document(food()))
    assert upload(client, b"\xef\xbb\xbf" + payload).status_code == 422
    assert db.session.query(UploadedFile).count() == db.session.query(NutritionImportDraft).count() == 0
    setup_qa(app)
    app.config["TESTING"] = True
    invalid = upload(client, payload.replace(b'"version": "1.0"', b'"version": "9.0"'))
    assert invalid.status_code == 422
    assert invalid.json["diagnostics"][0]["code"] == "unsupported_version"
    assert invalid.json["diagnostics"][0]["path"] == "/version"
    giant = upload(client, payload + b" " * intake.MAX_BYTES)
    assert giant.status_code == 413
    assert db.session.query(UploadedFile).count() == db.session.query(NutritionImportDraft).count() == 0
    assert not any(path.is_file() for path in Path(app.config["UPLOAD_ROOT"]).rglob("*"))


def test_review_expansion_limit_is_checked_before_storage(app, client, user, monkeypatch):
    setup_qa(app)
    login(client)
    monkeypatch.setattr(preparation, "MAX_REVIEW_BYTES", 8192)
    doc = document(food())
    doc["meals"][0]["foods"][0]["nutrition"]["values"]["energy"]["note"] = "QA " + "z" * 4000
    payload = bytes_of(doc)
    assert intake.parse(payload).profile == "htnx_1_0"
    response = upload(client, payload)
    assert response.status_code == 413
    assert response.json["diagnostics"][0]["code"] == "limit_exceeded"
    assert db.session.query(UploadedFile).count() == db.session.query(NutritionImportDraft).count() == 0
    assert not any(path.is_file() for path in Path(app.config["UPLOAD_ROOT"]).rglob("*"))


def test_exchange_prepares_reuses_and_recovers_only_compatible_same_owner_draft(app, client, user):
    app.config.update(NUTRITION_INTELLIGENCE_ENABLED=True)
    login(client)
    raw = bytes_of(spanish())
    legacy = row_for(user, upload(client, raw))
    setup_qa(app)
    current = row_for(user, upload(client, raw))
    assert current.id != legacy.id
    assert current.source_json["upload_id"] == legacy.source_json["upload_id"]
    assert row_for(user, upload(client, raw)).id == current.id
    assert db.session.query(UploadedFile).count() == 1
    assert not any(db.session.query(model).count() for model in (MealLog, FoodProduct, NutritionImportReceipt))
    frozen = deepcopy(current.review_json)
    current.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.session.commit()
    fresh = imports.recover(user, current.public_id, current.revision)
    assert fresh.id != current.id and current.review_json == frozen
    assert fresh.source_json["upload_id"] == current.source_json["upload_id"]
    assert fresh.source_json["decisions_reset"] is True


@pytest.mark.parametrize("with_legacy_original", [False, True])
def test_exchange_concurrent_same_bytes_reuse_one_draft(app, user, monkeypatch, with_legacy_original):
    if db.engine.dialect.name == "sqlite":
        pytest.skip("Requires independent MariaDB connections and row locks.")
    app.config.update(NUTRITION_INTELLIGENCE_ENABLED=True)
    raw = bytes_of(spanish())
    if with_legacy_original:
        imports.start(user, raw, "QA-ficticia.json", commit=True)
    setup_qa(app)
    original_extract = imports._extract_review
    gate = Barrier(2, timeout=12)

    def extract_before_lock(*args, **kwargs):
        found = original_extract(*args, **kwargs)
        # Establish a consistent snapshot in both transactions before either
        # takes the owner lock, including under REPEATABLE READ.
        db.session.scalar(select(NutritionImportDraft.id).limit(1))
        gate.wait()
        return found

    monkeypatch.setattr(imports, "_extract_review", extract_before_lock)

    def prepare(_):
        with app.app_context():
            return imports.start(user, raw, "QA-ficticia.json", commit=True).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(prepare, range(2))
    assert first == second
    assert db.session.query(UploadedFile).count() == 1
    assert db.session.query(NutritionImportDraft).count() == 1 + int(with_legacy_original)


def test_exchange_overlap_is_owner_local_and_blocks_projection(app, client, user):
    setup_qa(app)
    login(client)
    other = User(username="other-qa-owner", role="user")
    other.set_password("other-test-password")
    db.session.add(other)
    db.session.flush()
    target = date(2030, 2, 18)
    db.session.add(DailyNutrition(user_id=other.id, date=target, source="manual"))
    db.session.commit()
    raw = bytes_of(document(food()))
    unrelated = row_for(user, upload(client, raw))
    assert compact.overview(unrelated)["counts"]["ready"] == 1
    db.session.add(DailyNutrition(user_id=user, date=target, source="manual"))
    db.session.commit()
    # Different bytes must lead to another pending review of the possible overlap.
    row = row_for(user, upload(client, raw + b"\n"))
    record, = compact.overview(row)["records"]
    assert {d["code"] for d in record["diagnostics"]} == {"day_overlap"}
    assert record["state"] == "decision"
    with pytest.raises(NutritionError):
        projection.project(row)
    assert db.session.query(MealLog).count() == 0


def test_owner_and_revision_bound_decision_keeps_original_technical_only(app, client, user):
    setup_qa(app)
    login(client)
    doc = document(food({"amount": 2, "unit": "piece", "label": "pieza ficticia"}, {"amount": 100, "unit": "g"}))
    original = batch(doc).meals[0].foods[0]
    decision = normalize.FoodDecision(original, equivalence=normalize.Equivalence(Decimal(30), "Pesaje ficticio"))
    row = row_for(user, upload(client, bytes_of(doc)))
    revision = row.revision
    other = User(username="other-qa-owner", role="user")
    other.set_password("other-test-password")
    db.session.add(other)
    db.session.commit()
    with pytest.raises(NutritionError) as wrong_owner:
        imports.apply_exchange_decision(other.id, row.public_id, revision, decision)
    assert wrong_owner.value.status == 404
    db.session.rollback()
    changed = imports.apply_exchange_decision(user, row.public_id, revision, decision)
    db.session.commit()
    assert changed.revision == revision + 1
    with pytest.raises(NutritionError) as stale:
        imports.apply_exchange_decision(user, row.public_id, revision, decision)
    assert stale.value.status == 409
    assert db.session.query(MealLog).count() == db.session.query(NutritionImportReceipt).count() == 0
    assert db.session.scalar(select(UploadedFile)).sha256 == row.source_sha256


def test_failed_exchange_review_rolls_back_new_original_and_draft(app, client, user, monkeypatch):
    setup_qa(app)
    login(client)
    actual = imports._review_from_source

    def fail_late(*args, **kwargs):
        actual(*args, **kwargs)
        raise NutritionError("Fallo de QA tras preparar el borrador.")

    monkeypatch.setattr(imports, "_review_from_source", fail_late)
    assert upload(client, bytes_of(document(food()))).status_code == 422
    assert db.session.query(UploadedFile).count() == db.session.query(NutritionImportDraft).count() == 0
    assert not any(path.is_file() for path in Path(app.config["UPLOAD_ROOT"]).rglob("*"))
