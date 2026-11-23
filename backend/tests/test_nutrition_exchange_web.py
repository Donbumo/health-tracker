"""Universal exchange web workflow through the official test client and writer."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import re

import pytest

from app.extensions import db
from app.models import DailyNutrition, MealLog, NutritionImportDraft, NutritionImportReceipt, UploadedFile, User
from app.services import nutrition_import as imports, nutrition_import_review as compact
from app.services.importers.nutrition_exchange import intake
from tests.conftest import login
from tests.test_nutrition_import_source_21 import app
from tests.test_nutrition_import_summary import token


FIXTURE = Path(__file__).resolve().parents[2] / "examples/qa/nutrition-exchange/valid-explicit.json"


def enable(app):
    app.config.update(NUTRITION_INTELLIGENCE_ENABLED=True, NUTRITION_EXCHANGE_ENABLED=True)


def payload(document=None):
    return FIXTURE.read_bytes() if document is None else json.dumps(document, ensure_ascii=False).encode()


def upload(client, user, original, *, paste=False):
    data = {"exchange_json": original.decode()} if paste else {"file": (BytesIO(original), "QA ficticia.json")}
    response = client.post("/nutrition/import", data=data)
    assert response.status_code == 302, response.text[:1200]
    return imports.owned(user, response.location.rsplit("/", 1)[-1])


def decide(client, row, action, **fields):
    response = client.post(f"/nutrition/import/{row.public_id}/exchange-decision",
                           data={"revision": row.revision, "action": action, **fields})
    assert response.status_code == 302, response.text[:1200]
    db.session.refresh(row)
    return compact.overview(row)


def small_doc():
    doc = json.loads(payload())
    return dict(doc, meals=doc["meals"][:1])


def test_entry_requires_explicit_flag_and_authentication(app, client, user):
    app.config.update(NUTRITION_INTELLIGENCE_ENABLED=True)
    login(client)
    assert "Importar comidas con IA" not in client.get("/nutrition/import").text
    assert client.post("/nutrition/import", data={"exchange_json": payload().decode()}).status_code == 422
    assert client.get("/nutrition/import/exchange/1.0/example").status_code == 404
    enable(app)
    app.config["TESTING"] = False
    page = client.get("/nutrition/import")
    assert page.status_code == 200
    assert all(term in page.text for term in ("Importar comidas con IA", "Copiar prompt para IA", "Descargar ejemplo", "Pegar JSON"))
    example = client.get("/nutrition/import/exchange/1.0/example")
    assert intake.parse(example.data).profile == "htnx_1_0"
    assert "no-store" in example.headers["Cache-Control"]
    assert client.get("/nutrition/import/exchange/1.0/schema").json["title"].endswith("1.0")
    with app.app_context():
        assert app.test_client().get("/nutrition/import/exchange/1.0/example").status_code == 302


def test_paste_upload_preview_and_final_consent_are_separate(app, client, user):
    enable(app)
    login(client)
    row = upload(client, user, payload(), paste=True)
    replay = upload(client, user, payload())
    assert replay.id == row.id
    assert db.session.query(UploadedFile).count() == 1
    page = client.get(f"/nutrition/import/{row.public_id}")
    assert page.status_code == 200
    assert "4 listos · 0 pendientes · 0 inválidos" in page.text
    assert "No proporcionado" in page.text and "Desconocido" in page.text and "Traza" in page.text
    assert "Bajo el límite" in page.text and "Declarado · 0 g" in page.text
    assert "570.125" in page.text and "Cromo" in page.text
    assert db.session.query(MealLog).count() == 0
    url = f"/nutrition/import/{row.public_id}/confirm"
    fields = {"revision": row.revision, "token": token(client, row)}
    assert client.post(url, data=fields).status_code == 422
    assert db.session.query(NutritionImportReceipt).count() == 0
    assert client.post(url, data=dict(fields, consent_consumed="yes")).status_code == 200
    assert client.post(url, data=dict(fields, consent_consumed="yes")).status_code == 200
    assert db.session.query(MealLog).count() == 4
    assert db.session.query(NutritionImportReceipt).count() == 1


def test_grouped_basis_only_applies_to_matching_unresolved_rows(app, client, user):
    enable(app)
    login(client)
    doc = small_doc()
    original = doc["meals"][0]["foods"][0]
    foods = [dict(deepcopy(original), name=f"Alimento ficticio {i}") for i in range(18)]
    for food in foods[:17]:
        del food["nutrition"]["basis"]
    foods[17]["nutrition"]["basis"]["unit"] = "ml"
    doc["meals"][0]["foods"] = foods
    row = upload(client, user, payload(doc))
    proposal = compact.overview(row)["exchange_groups"]["g"]
    assert len(proposal["paths"]) == 17
    view = decide(client, row, "group", unit="g", verified="yes", context=proposal["witness"])
    assert view["counts"] == {"ready": 17, "decision": 1, "invalid": 0, "omitted": 0}
    assert view["records"][17]["preview"] is None
    assert view["records"][17]["declared_values"]["energy"]["value"] == "130"
    assert db.session.query(MealLog).count() == 0


def test_destination_meal_quantity_basis_and_equivalence(app, client, user):
    enable(app)
    login(client)
    doc = small_doc()
    doc.pop("destination")
    doc.pop("date")
    meal = doc["meals"][0]
    meal.pop("type")
    food = meal["foods"][0]
    food.pop("quantity")
    row = upload(client, user, payload(doc))
    decide(client, row, "destination", destination="consumed")
    decide(client, row, "meal", index=0, date="2030-01-15", meal_type="lunch")
    decide(client, row, "quantity", index=0, quantity_amount="2", quantity_unit="piece", quantity_label="pieza de QA")
    view = decide(client, row, "equivalence", index=0, factor="20", source="Pesaje ficticio QA", verified="yes")
    assert view["counts"]["ready"] == 1
    assert Decimal(view["batch_summary"]["energy"]["value"]) == 52
    stale_token = token(client, row)
    view = decide(client, row, "quantity", index=0, quantity_amount="3", quantity_unit="piece", quantity_label="pieza de QA")
    assert view["counts"]["decision"] == 1
    assert view["records"][0]["preview"] is None
    assert client.post(f"/nutrition/import/{row.public_id}/confirm", data={
        "revision": row.revision, "token": stale_token, "consent_consumed": "yes",
    }).status_code == 409
    view = decide(client, row, "basis", index=0, basis_kind="consumed")
    assert Decimal(view["batch_summary"]["energy"]["value"]) == 130
    evidence = compact.document(row)["data"]["entries"][0]["declaration"]["provenance"]["source_provenance"]
    assert evidence["food"]["quantity"] is None
    assert evidence["food"]["nutrition"]["basis"]["amount"] == "100"


def test_authority_choice_uses_one_source(app, client, user):
    enable(app)
    login(client)
    doc = json.loads(FIXTURE.with_name("valid-needs-review.json").read_bytes())
    doc = dict(doc, destination="consumed", meals=doc["meals"][1:])
    row = upload(client, user, payload(doc))
    assert "Fuente del aporte" in client.get(f"/nutrition/import/{row.public_id}").text
    view = decide(client, row, "authority", index=0, choice="ingredients")
    assert view["counts"]["ready"] == 1
    assert Decimal(view["batch_summary"]["energy"]["value"]) == 110
    assert db.session.query(MealLog).count() == 0


def test_overlap_requires_independent_decision_from_duplicate(app, client, user):
    enable(app)
    login(client)
    doc = small_doc()
    row = upload(client, user, payload(doc))
    url = f"/nutrition/import/{row.public_id}/confirm"
    assert client.post(url, data={"revision": row.revision, "token": token(client, row), "consent_consumed": "yes"}).status_code == 200
    doc["note"] = "Segundo archivo ficticio con los mismos datos"
    row = upload(client, user, payload(doc))
    item = compact.overview(row)["records"][0]["item"]
    assert item["exchange_duplicate"]["matches"][0][1] == "En tu historial"
    view = decide(client, row, "duplicate", index=0, choice="distinct", context=item["exchange_duplicate"]["witness"])
    assert view["counts"]["decision"] == 1
    assert view["records"][0]["issues"][0]["code"] == "day_overlap"
    item = view["records"][0]["item"]
    view = decide(client, row, "day", date=item["date"], verified="yes", context=item["exchange_day"]["witness"])
    assert view["counts"]["ready"] == 1
    assert db.session.query(MealLog).count() == 1


def test_explicit_omit_preserves_peer_and_legacy_aggregate(app, client, user):
    enable(app)
    login(client)
    doc = small_doc()
    doc["meals"][0]["foods"] *= 2
    target = date.fromisoformat(doc["date"])
    db.session.add(DailyNutrition(user_id=user, source="manual", date=target, calories=60))
    db.session.commit()
    row = upload(client, user, payload(doc))
    item, peer = [record["item"] for record in compact.overview(row)["records"]]
    decide(client, row, "duplicate", index=0, choice="omit", context=item["exchange_duplicate"]["witness"])
    view = decide(client, row, "duplicate", index=1, choice="distinct", context=peer["exchange_duplicate"]["witness"])
    page = client.get(f"/nutrition/import/{row.public_id}")
    assert "Conservar el registro previo y añadir" in page.text
    item = view["records"][1]["item"]
    view = decide(client, row, "day", date=item["date"], verified="yes", context=item["exchange_day"]["witness"])
    assert view["counts"] == {"ready": 1, "decision": 0, "invalid": 0, "omitted": 1}
    assert compact.document(row)["data"]["entries"][0]["authority"] == "disjoint_aggregate"
    assert Decimal(view["batch_summary"]["energy"]["value"]) == 195
    assert db.session.query(DailyNutrition).one().calories == 60


def test_csrf_owner_stale_revision_and_original_integrity(app, client, user):
    enable(app)
    login(client)
    row = upload(client, user, payload())
    url = f"/nutrition/import/{row.public_id}/exchange-decision"
    form = {"revision": row.revision, "action": "quantity", "index": 0,
            "quantity_amount": "85", "quantity_unit": "g"}
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post(url, data=form).status_code == 400
    app.config["WTF_CSRF_ENABLED"] = False
    other = User(username="exchange-qa-other", role="user")
    other.set_password("fictional-other-password")
    db.session.add(other)
    db.session.commit()
    with app.app_context():
        foreign = app.test_client()
        login(foreign, username="exchange-qa-other", password="fictional-other-password")
        assert foreign.post(url, data=form).status_code == 404
    decide(client, row, "quantity", index=0, quantity_amount="85", quantity_unit="g")
    assert client.post(url, data=form).status_code == 409
    from app.services.backups import resolve_uploaded_download

    original = resolve_uploaded_download(db.session.query(UploadedFile).one(), user_id=user)
    original.write_bytes(b"synthetic altered original")
    assert client.get(f"/nutrition/import/{row.public_id}").status_code == 409
    assert db.session.query(MealLog).count() == 0


def test_html_diagnostics_and_expired_recovery(app, client, user):
    enable(app)
    login(client)
    malformed = client.post("/nutrition/import", data={"exchange_json": '{"format":"health-tracker-nutrition","version":"9"}'})
    assert malformed.status_code == 422 and "/version" in malformed.text
    assert db.session.query(NutritionImportDraft).count() == db.session.query(UploadedFile).count() == 0
    row = upload(client, user, payload())
    original = deepcopy(row.review_json)
    row.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.session.commit()
    assert "REVISIÓN VENCIDA" in client.get(f"/nutrition/import/{row.public_id}").text
    response = client.post(f"/nutrition/import/{row.public_id}/recover", data={"revision": row.revision})
    assert response.status_code == 302 and row.public_id not in response.location
    assert row.review_json == original
    assert db.session.query(UploadedFile).count() == 1
    assert db.session.query(MealLog).count() == 0


def test_unexpected_exchange_failure_has_sanitized_incident(app, client, user, monkeypatch):
    from app.services.importers.nutrition_exchange import preparation

    enable(app)
    login(client)

    def interrupted(*args, **kwargs):
        raise RuntimeError("unreported-fictional-payload")

    logged = []
    monkeypatch.setattr(app.logger, "error", lambda message, *args: logged.append(message % args))
    monkeypatch.setattr(preparation.normalize, "evaluate", interrupted)
    response = client.post("/nutrition/import", data={"exchange_json": payload().decode()})
    assert response.status_code == 500
    reference = re.search(r"Referencia de incidencia ([0-9a-f-]{36})", response.text)
    assert reference and logged == [f"nutrition_exchange_error request_id={reference[1]} type=RuntimeError"]
    assert "unreported-fictional-payload" not in response.text
    assert db.session.query(NutritionImportDraft).count() == db.session.query(UploadedFile).count() == 0


@pytest.mark.parametrize("provider,expects_label", [("gemini", True), ("perplexity", False)])
def test_independent_provider_output_through_official_preview(app, client, user, provider, expects_label):
    enable(app)
    login(client)
    original = (FIXTURE.parent / "providers" / f"{provider}.json").read_bytes()
    row = upload(client, user, original, paste=True)
    view = compact.overview(row)
    assert view["counts"] == {"ready": 2, "decision": 0, "invalid": 0, "omitted": 0}
    assert Decimal(view["batch_summary"]["energy"]["value"]) == Decimal("260.125")
    assert Decimal(view["batch_summary"]["protein"]["value"]) == Decimal("4.05")
    page = client.get(f"/nutrition/import/{row.public_id}")
    assert page.status_code == 200
    assert all(text in page.text for text in ("Tabla ficticia QA", "Traza", "Bajo el límite", "Desconocido", "Declarado · 0 g"))
    assert ("Etiqueta declarada" in page.text) is expects_label
    assert db.session.query(MealLog).count() == db.session.query(NutritionImportReceipt).count() == 0


def test_authentic_markdown_clipboard_paste_and_upload_keep_original(app, client, user):
    from hashlib import sha256

    from app.services.backups import resolve_uploaded_download
    from app.services.nutrition_math import NUTRIENTS

    enable(app)
    login(client)
    original = (FIXTURE.parent / "providers/chatgpt.clipboard.txt").read_bytes()
    row = upload(client, user, original, paste=True)
    replay = upload(client, user, original)
    assert replay.id == row.id
    assert row.source_json["profile"] == "htnx_1_0"
    stored = db.session.query(UploadedFile).one()
    assert stored.sha256 == sha256(original).hexdigest()
    assert resolve_uploaded_download(stored, user_id=user).read_bytes() == original
    view = compact.overview(row)
    assert view["counts"] == {"ready": 2, "decision": 1, "invalid": 0, "omitted": 0}
    first, second, pending = view["records"]
    assert first["item"]["exchange_input"]["quantity"]["amount"] == "125.125"
    assert first["item"]["exchange_input"]["basis"]["amount"] == "100"
    assert first["item"]["exchange_input"]["basis"]["unit"] == "g"
    assert second["item"]["exchange_input"]["quantity"]["unit"] == "portion"
    assert second["item"]["exchange_input"]["basis_kind"] == "consumed"
    assert pending["item"]["exchange_input"]["quantity"]["unit"] == "piece"
    assert pending["preview"] is None
    assert set(first["preview"]) == set(view["batch_summary"]) == NUTRIENTS.keys()
    expected = {
        "energy": "130.125", "protein": "2.75", "carbohydrate_total": "18.5", "net_carbs": "16.25",
        "fat": "4.75", "fiber": "2.25", "sugar": "1.5", "sodium": "120.25", "potassium": "150.5",
        "calcium": "200.25", "iron": "2.125", "magnesium": "30.5", "phosphorus": "70.25", "zinc": "1.125",
        "vitamin_c": "3.25", "vitamin_e_alpha": "4.125", "thiamin": "0.125", "riboflavin": "0.25",
        "niacin": "1.5", "vitamin_b6": "0.75", "choline": "8.25", "vitamin_a_rae": "12.5",
        "retinol": "3.25", "vitamin_a_re": "11.5", "vitamin_d": "0.875", "vitamin_k1": "2.5",
        "vitamin_k2": "1.25", "vitamin_b12": "0.375", "folate_dfe": "21.25", "folate_food": "18.5",
    }
    assert expected.keys() == NUTRIENTS.keys()
    for key, source in expected.items():
        nutrient = first["preview"][key]
        assert nutrient["unit"] == NUTRIENTS[key][1]
        assert Decimal(nutrient["value"]) == Decimal(source) * Decimal("1.25125")
    observations = first["item"]["source_provenance"]["food"]["nutrition"]["observations"]
    assert observations["energy"]["quality"] == "label" and observations["protein"]["quality"] == "estimated"
    sparse = second["item"]["source_provenance"]["food"]["nutrition"]["observations"]
    assert set(sparse) == {"energy", "potassium", "iron", "vitamin_d"}
    assert Decimal(sparse["energy"]["value"]) == 0
    assert sparse["potassium"]["state"] == "unknown" and sparse["iron"]["state"] == "trace"
    assert sparse["vitamin_d"]["state"] == "below_limit" and Decimal(sparse["vitamin_d"]["limit"]) == Decimal("0.2")
    assert Decimal(view["batch_summary"]["energy"]["value"]) == Decimal("162.81890625")
    assert Decimal(view["batch_summary"]["protein"]["value"]) == Decimal("3.4409375")
    page = client.get(f"/nutrition/import/{row.public_id}")
    assert page.status_code == 200
    for caption in ("Etiqueta ficticia QA Alfa", "Estimado", "Etiqueta declarada", "Traza", "Cromo",
                    "Bajo el límite", "Desconocido", "No proporcionado", "Declarado · 72.5 kcal"):
        assert caption in page.text
    assert not re.search(r'name="consent_consumed"[^>]*checked', page.text)
    assert re.search(r'<button[^>]*disabled[^>]*>Guardar todo</button>', page.text)
    assert db.session.query(MealLog).count() == db.session.query(NutritionImportReceipt).count() == 0


@pytest.mark.parametrize("pattern,replacement,code", [
    (b'"version": "1.0"', b'"version": "9.9"', "unsupported_version"),
    (b'"version": "1.0"', b'"version": "1.0", "version": "1.0"', "duplicate_key"),
    (b'"version": "1.0"', b'"version": "1.0", "unexpected": 1', "schema_error"),
])
def test_clipboard_transport_does_not_relax_htnx_validation(app, client, user, pattern, replacement, code):
    enable(app)
    login(client)
    raw = (FIXTURE.parent / "providers/chatgpt.clipboard.txt").read_bytes()
    rejected = client.post("/nutrition/import", data={"exchange_json": raw.replace(pattern, replacement).decode()},
                           headers={"Accept": "application/json"})
    assert rejected.status_code == 422
    assert code in {entry["code"] for entry in rejected.json["diagnostics"]}
    assert db.session.query(UploadedFile).count() == db.session.query(NutritionImportDraft).count() == 0


def test_clipboard_conversion_preserves_literal_backslashes_and_requires_array_pattern(app, client, user):
    enable(app)
    login(client)
    raw = (FIXTURE.parent / "providers/chatgpt.clipboard.txt").read_bytes()
    edited = raw.replace(b'"destination":', br'"note": "literal \\[QA\\] and \\_QA", "destination":', 1)
    row = upload(client, user, edited)
    assert compact.overview(row)["counts"]["ready"] == 2
    from app.services.importers.nutrition_exchange.preparation import _parse_exchange

    assert _parse_exchange(edited).document["note"] == r"literal \[QA\] and \_QA"
    invalid = payload().replace(b'"note": "', br'"note": "\_ ', 1)
    response = client.post("/nutrition/import", data={"exchange_json": invalid.decode()},
                           headers={"Accept": "application/json"})
    assert response.status_code == 422
    assert response.json["diagnostics"][0]["code"] == "invalid_json"
