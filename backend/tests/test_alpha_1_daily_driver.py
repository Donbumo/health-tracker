import io
import json
import re
from datetime import date, datetime, timezone
from html import unescape

from app.extensions import db
from app.models import DailyEnergy, PlannedWorkout, TrainingPlan, TrainingPlanVersion, User, WeighIn
from app.services.account_restore import AccountRestoreService
from app.services.exporters.user_data import build_user_data_document
from app.services.importers.registry import ImportAdapterRegistry
from app.services.validation import validate_json_document
from tests.conftest import login


def _hidden(response, name: str) -> str:
    match = re.search(
        rb'name="' + name.encode() + rb'"[^>]*value="([^"]*)"', response.data
    )
    if match is None:
        match = re.search(
            rb'value="([^"]*)"[^>]*name="' + name.encode() + rb'"', response.data
        )
    assert match is not None, name
    return unescape(match.group(1).decode())


def _plan_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {
            "name": "Rutina cotidiana ficticia",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Día ficticio",
                            "exercises": [],
                        }
                    ],
                }
            ],
        },
    }


def test_getting_started_and_preferences_are_authenticated_and_owner_scoped(app, client, user):
    assert client.get("/getting-started").status_code == 302
    assert client.get("/account/preferences").status_code == 302

    login(client)
    page = client.get("/getting-started")
    assert page.status_code == 200
    assert b"Los estados se calculan desde tus datos reales" in page.data
    assert b"Registrar un dispositivo API" in page.data

    response = client.post(
        "/account/preferences",
        data={
            "display_name": "Persona QA ficticia",
            "timezone": "America/Mexico_City",
            "preferred_load_unit": "lb",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Preferencias guardadas" in response.data
    with app.app_context():
        account = db.session.get(User, user)
        assert account.display_name == "Persona QA ficticia"
        assert account.timezone == "America/Mexico_City"
        assert account.preferred_load_unit == "lb"


def test_invalid_timezone_is_rejected_without_changing_preferences(app, client, user):
    login(client)
    response = client.post(
        "/account/preferences",
        data={
            "display_name": "Nombre ficticio",
            "timezone": "Not/A_Real_Timezone",
            "preferred_load_unit": "kg",
        },
    )
    assert response.status_code == 200
    assert b"zona horaria IANA" in response.data
    with app.app_context():
        assert db.session.get(User, user).timezone is None


def test_existing_user_data_does_not_displace_daily_dashboard(app, client, user):
    with app.app_context():
        db.session.add(
            WeighIn(
                user_id=user,
                recorded_at=datetime.now(timezone.utc),
                weight_kg="75.0",
                source="manual",
            )
        )
        db.session.commit()
    login(client)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Dashboard diario" in html
    assert "Entrenamiento de hoy" in html
    assert "Continuar primeros pasos" not in html


def test_dashboard_shows_owned_planned_workout_as_primary_action(app, client, user):
    with app.app_context():
        plan = TrainingPlan(user_id=user, name="Rutina QA de hoy")
        db.session.add(plan)
        db.session.flush()
        version = TrainingPlanVersion(
            user_id=user,
            training_plan_id=plan.id,
            version_number=1,
            created_by_user_id=user,
            schema_version="1.0",
            sha256="a" * 64,
            content=_plan_document(user),
        )
        db.session.add(version)
        db.session.flush()
        db.session.add(
            PlannedWorkout(
                user_id=user,
                training_plan_id=plan.id,
                training_plan_version_id=version.id,
                scheduled_for_date=date.today(),
                timezone="UTC",
                title_snapshot="Día ficticio de hoy",
                payload_snapshot_json={"name": "Día ficticio de hoy", "exercises": []},
                source_version=1,
            )
        )
        db.session.commit()
    login(client)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Día ficticio de hoy" in html
    assert "Empezar" in html
    assert "Rutina QA de hoy" in html


def test_import_hub_json_preview_confirm_and_history_link(app, client, user):
    assert client.get("/imports").status_code == 302
    login(client)
    payload = {
        "energia": [{"fecha": "2026-08-01", "calorias_totales": 2300}]
    }
    preview = client.post(
        "/imports",
        data={
            "requested_type": "daily_energy",
            "file": (io.BytesIO(json.dumps(payload).encode()), "energia.json"),
        },
        content_type="multipart/form-data",
    )
    assert preview.status_code == 200
    assert b"Revisi" in preview.data
    assert b"Confirmar importaci" in preview.data
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []

    response = client.post(
        "/imports",
        data={
            "mode": _hidden(preview, "mode"),
            "payload_json": _hidden(preview, "payload_json"),
            "source_file_id": _hidden(preview, "source_file_id"),
            "requested_type": _hidden(preview, "requested_type"),
            "target_type": _hidden(preview, "target_type"),
            "confirmation_token": _hidden(preview, "confirmation_token"),
        },
    )
    assert response.status_code == 200
    assert b"Resultado" in response.data
    assert b"Ver reporte" in response.data
    with app.app_context():
        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert record.user_id == user
        assert record.date.isoformat() == "2026-08-01"


def test_import_hub_preselects_supported_type(app, client, user):
    login(client)
    response = client.get("/imports?requested_type=training_plan")
    assert response.status_code == 200
    assert b'<option selected value="training_plan">' in response.data


def test_guided_plan_creation_and_duplicate_are_owner_scoped(app, client, user):
    login(client)
    response = client.post(
        "/training-plans/new",
        data={
            "name": "Rutina guiada ficticia",
            "description": "Rutina creada desde el formulario guiado.",
            "day_name": "Día A",
            "exercise_name": "Sentadilla ficticia",
            "set_count": "3",
            "target_reps": "8",
            "rest_seconds": "120",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        plan = db.session.execute(
            db.select(TrainingPlan).where(TrainingPlan.user_id == user)
        ).scalar_one()
        assert plan.active_version_number == 1
        content = plan.versions[0].content
        assert len(content["data"]["weeks"][0]["days"][0]["exercises"][0]["sets"]) == 3
        plan_id = plan.id

    duplicated = client.post(
        f"/training-plans/{plan_id}/duplicate",
        data={"name": "Copia ficticia independiente"},
    )
    assert duplicated.status_code == 302
    with app.app_context():
        plans = db.session.execute(
            db.select(TrainingPlan)
            .where(TrainingPlan.user_id == user)
            .order_by(TrainingPlan.name)
        ).scalars().all()
        assert {item.name for item in plans} == {
            "Rutina guiada ficticia",
            "Copia ficticia independiente",
        }
        assert plans[0].id != plans[1].id


def test_history_and_agenda_filters_render_without_leaking_other_user(app, client, user):
    with app.app_context():
        other = User(username="other-alpha10", role="user")
        other.set_password("test-password")
        db.session.add(other)
        db.session.flush()
        other_plan = TrainingPlan(user_id=other.id, name="Rutina ajena invisible")
        db.session.add(other_plan)
        db.session.commit()
    login(client)
    history = client.get(
        "/training-sessions?date_from=2026-01-01&date_to=2026-12-31&exercise=remo"
    )
    assert history.status_code == 200
    assert b"Filtrar historial" in history.data
    assert b'<input id="exercise" name="exercise" type="text"' in history.data
    assert b"Rutina ajena invisible" not in history.data
    agenda = client.get(
        "/planned-workouts?date_from=2026-01-01&date_to=2026-12-31&status=planned"
    )
    assert agenda.status_code == 200
    assert b"Filtrar agenda" in agenda.data


def test_preferences_export_validate_and_restore_to_destination(app, user):
    with app.app_context():
        source = db.session.get(User, user)
        source.display_name = "Persona portable ficticia"
        source.timezone = "America/Mexico_City"
        source.preferred_load_unit = "lb"
        destination = User(username="portable-destination", role="user")
        destination.set_password("test-password")
        db.session.add(destination)
        db.session.commit()
        destination_id = destination.id

        payload = build_user_data_document(source, user)
        validate_json_document(payload, "user_data_export")
        service = AccountRestoreService()
        preview = service.preview(payload, user_id=destination_id)
        result = service.commit(
            payload,
            user_id=destination_id,
            confirmation_token=preview["confirmation_token"],
        )
        assert result["committed"] is True
        restored = db.session.get(User, destination_id)
        assert restored.display_name == "Persona portable ficticia"
        assert restored.timezone == "America/Mexico_City"
        assert restored.preferred_load_unit == "lb"
        assert restored.username == "portable-destination"


def test_pwa_contract_caches_only_static_assets(app, client):
    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.get_json()["display"] == "standalone"
    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    text = worker.get_data(as_text=True)
    assert 'url.pathname.startsWith("/static/")' in text
    assert "request.method !== \"GET\"" in text
    assert "/api/" not in text


def test_import_adapter_registry_matches_visible_supported_pipelines(app, client, user):
    registry = ImportAdapterRegistry()
    assert {spec.adapter_id for spec in registry.specs} == {
        "standard_json",
        "activity_files",
        "wellness_csv",
    }
    assert registry.get("standard_json").max_bytes == 10 * 1024 * 1024
    login(client)
    response = client.get("/imports")
    assert response.status_code == 200
    assert b"Formatos compatibles" in response.data
    assert b".fit, .gpx, .tcx" in response.data
    assert b"Importaciones recientes" in response.data
