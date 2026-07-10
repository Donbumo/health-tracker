import io
import json
import re
from html import unescape

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    DailyEnergy,
    FoodProduct,
    ImportRun,
    Recipe,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    User,
)
from app.services.import_audit import ImportAuditService, sanitize_error
from app.services.importers.standard_import_executor import (
    StandardImportExecutor,
    canonical_sha256,
)
from tests.conftest import login


def _energy_document(user_id: int, date_value: str = "2026-09-01") -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "date": date_value,
            "source": "qa",
            "total_expenditure_kcal": 2400,
            "notes": "nota privada ficticia que no debe aparecer en auditoria",
        },
    }


def _training_plan_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": "Plan audit QA",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Dia audit QA",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Press audit QA",
                                    "sets": [{"set_number": 1, "reps": 8}],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }


def _completed_workout_document(user_id: int, plan_id: int, version_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "training_plan_id": plan_id,
            "training_plan_version_id": version_id,
            "performed_at": "2026-09-02T18:00:00+00:00",
            "planned_week_number": 1,
            "planned_day_number": 1,
            "exercises": [
                {
                    "exercise_order": 1,
                    "planned_exercise_order": 1,
                    "name": "Press audit QA",
                    "sets": [
                        {
                            "set_number": 1,
                            "planned_set_number": 1,
                            "weight_kg": 50,
                            "reps": 8,
                        }
                    ],
                }
            ],
        },
    }


def _recipe_document(user_id: int, name: str) -> dict:
    return {
        "schema_version": "1.0",
        "type": "recipe",
        "user_id": user_id,
        "source_type": "uploaded",
        "name": name,
        "servings": 2,
        "ingredients": [
            {
                "food_product_name": "Producto audit QA",
                "quantity_g": 50,
            }
        ],
    }


def _recipe_bundle_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "type": "recipe_bundle",
        "user_id": user_id,
        "source_type": "uploaded",
        "name": "Bundle audit QA",
        "recipes": [
            _recipe_document(user_id, "Receta audit uno"),
            _recipe_document(user_id, "Receta audit dos"),
        ],
    }


def _seed_food_product(user_id: int) -> None:
    db.session.add(
        FoodProduct(
            user_id=user_id,
            name="Producto audit QA",
            source="qa",
            calories_per_100g=100,
            is_active=True,
        )
    )
    db.session.commit()


def _seed_plan(user_id: int) -> tuple[TrainingPlan, TrainingPlanVersion]:
    executor = StandardImportExecutor()
    executor.commit_documents(
        [_training_plan_document(user_id)],
        user_id=user_id,
        target_type="training_plan",
        confirmed=True,
    )
    plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
    version = db.session.execute(db.select(TrainingPlanVersion)).scalar_one()
    return plan, version


def _hidden(response, name: str) -> str:
    match = re.search(
        rb'name="' + name.encode() + rb'"\s+type="hidden"\s+value="([^"]*)"',
        response.data,
    )
    if match is None:
        match = re.search(
            rb'type="hidden"\s+[^>]*name="' + name.encode() + rb'"[^>]*value="([^"]*)"',
            response.data,
        )
    assert match is not None, response.data.decode("utf-8", errors="replace")
    return unescape(match.group(1).decode("utf-8"))


def _preview(client, payload: dict, target_type: str = "daily_energy"):
    return client.post(
        "/imports/standard",
        data={
            "target_type": target_type,
            "file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "payload.json"),
        },
        content_type="multipart/form-data",
    )


def _confirm_data(preview_response):
    return {
        "payload_json": _hidden(preview_response, "payload_json"),
        "target_type": _hidden(preview_response, "target_type"),
        "confirmation_token": _hidden(preview_response, "confirmation_token"),
    }


def test_import_run_model_defaults_relationship_and_constraints(app, user):
    with app.app_context():
        run = ImportRun(
            user_id=user,
            target_type="daily_energy",
            source_type="uploaded",
            payload_sha256="a" * 64,
            plan_sha256="b" * 64,
        )
        db.session.add(run)
        db.session.commit()

        assert run.id is not None
        assert run.status == "pending"
        assert run.total_count == 0
        assert run.user.id == user

        invalid = ImportRun(
            user_id=user,
            target_type="daily_energy",
            status="not-valid",
            payload_sha256="c" * 64,
            plan_sha256="d" * 64,
        )
        db.session.add(invalid)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_import_audit_service_allows_only_safe_metadata_and_sanitizes_errors(app, user):
    summary = {
        "total": 1,
        "inserts": 1,
        "updates": 0,
        "skips": 0,
        "conflicts": 0,
        "invalid": 0,
        "operations": [{"operation": "insert", "label": "dato privado"}],
    }

    with app.app_context():
        service = ImportAuditService()
        run = service.create_pending(
            user_id=user,
            target_type="daily_energy",
            source_type="uploaded",
            payload_sha256="a" * 64,
            plan_sha256="b" * 64,
            summary=summary,
            metadata={
                "route": "/imports/standard",
                "source_path": "energia",
                "payload": {"private": True},
                "token": "secret-token",
                "notes": "nota privada",
            },
        )
        service.finalize_succeeded(run, summary)
        db.session.commit()

        assert run.status == "succeeded"
        assert run.completed_at is not None
        assert run.metadata_json["route"] == "/imports/standard"
        assert run.metadata_json["source_path"] == "energia"
        assert run.metadata_json["operation_names"] == ["insert"]
        assert "payload" not in run.metadata_json
        assert "token" not in run.metadata_json
        assert "nota privada" not in json.dumps(run.metadata_json)

    assert "\n" not in sanitize_error("line 1\nline 2")
    assert len(sanitize_error("x" * 800)) == 500


def test_confirmed_import_audits_success_skip_blocked_and_hashes(app, user):
    with app.app_context():
        executor = StandardImportExecutor()
        payload = {"energia": [{"fecha": "2026-09-01", "calorias_totales": 2400}]}
        document = _energy_document(user)
        invalid = _energy_document(user, date_value="2026-09-02")
        del invalid["data"]["date"]

        first = executor.commit_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
            audit_payload=payload,
            audit_metadata={"route": "/imports/standard", "mode": "unit"},
        )
        repeated = executor.commit_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        blocked = executor.commit_documents(
            [invalid],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        runs = db.session.execute(
            db.select(ImportRun).order_by(ImportRun.id)
        ).scalars().all()
        assert [run.status for run in runs] == ["succeeded", "succeeded", "blocked"]
        assert first["audit_run_id"] == runs[0].id
        assert repeated["audit_run_id"] == runs[1].id
        assert blocked["audit_run_id"] == runs[2].id
        assert runs[0].payload_sha256 == canonical_sha256(payload)
        assert runs[0].insert_count == 1
        assert runs[1].skip_count == 1
        assert runs[2].invalid_count == 1
        assert runs[2].error_message == "Import contains invalid or conflicting documents."
        assert "nota privada" not in json.dumps([run.metadata_json for run in runs])


def test_batch_invalid_import_creates_blocked_audit_without_domain_rows(app, user):
    with app.app_context():
        valid = _energy_document(user, date_value="2026-09-20")
        invalid = _energy_document(user, date_value="2026-09-21")
        del invalid["data"]["date"]

        result = StandardImportExecutor().commit_documents(
            [valid, invalid],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        run = db.session.execute(db.select(ImportRun)).scalar_one()
        assert result["committed"] is False
        assert run.status == "blocked"
        assert run.total_count == 2
        assert run.insert_count == 1
        assert run.invalid_count == 1
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_recipe_bundle_audit_counts_embedded_recipe_operations(app, user):
    with app.app_context():
        _seed_food_product(user)
        bundle = _recipe_bundle_document(user)
        executor = StandardImportExecutor()

        first = executor.commit_documents(
            [bundle],
            user_id=user,
            target_type="recipe_bundle",
            confirmed=True,
        )
        repeated = executor.commit_documents(
            [bundle],
            user_id=user,
            target_type="recipe_bundle",
            confirmed=True,
        )

        runs = db.session.execute(
            db.select(ImportRun).order_by(ImportRun.id)
        ).scalars().all()
        assert first["inserts"] == 2
        assert repeated["skips"] == 2
        assert runs[0].insert_count == 2
        assert runs[0].total_count == 2
        assert runs[1].skip_count == 2
        assert db.session.execute(db.select(Recipe)).scalars().all()


def test_failed_import_rolls_back_domain_data_but_persists_failed_run(app, user, monkeypatch):
    with app.app_context():
        executor = StandardImportExecutor()
        documents = [
            _energy_document(user, date_value="2026-09-03"),
            _energy_document(user, date_value="2026-09-04"),
        ]
        original_apply = executor._apply_document
        calls = {"count": 0}

        def fail_after_first(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated private lab value should be sanitized enough")
            return original_apply(*args, **kwargs)

        monkeypatch.setattr(executor, "_apply_document", fail_after_first)
        result = executor.commit_documents(
            documents,
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        assert result["committed"] is False
        assert result["rollback"] is True
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []
        run = db.session.execute(db.select(ImportRun)).scalar_one()
        assert run.status == "failed"
        assert run.total_count == 2
        assert run.error_code == "write_failed"
        assert result["errors"] == [
            "Import write failed; all domain changes were rolled back."
        ]
        assert "private lab value" not in run.error_message
        assert "Traceback" not in run.error_message


def test_pending_audit_run_is_persisted_before_domain_mutation(app, user, monkeypatch):
    with app.app_context():
        executor = StandardImportExecutor()
        original_apply = executor._apply_document
        observed = {"pending": False}

        def observe_pending(*args, **kwargs):
            observed["pending"] = db.session.execute(
                db.select(ImportRun).where(
                    ImportRun.status == "pending",
                    ImportRun.user_id == user,
                )
            ).scalar_one_or_none() is not None
            return original_apply(*args, **kwargs)

        monkeypatch.setattr(executor, "_apply_document", observe_pending)
        result = executor.commit_documents(
            [_energy_document(user, date_value="2026-09-30")],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        run = db.session.get(ImportRun, result["audit_run_id"])
        assert observed["pending"] is True
        assert run.status == "succeeded"


def test_audit_finalization_failure_rolls_back_domain_and_marks_existing_run_failed(
    app,
    user,
    monkeypatch,
):
    with app.app_context():
        executor = StandardImportExecutor()

        def fail_finalize(*_args, **_kwargs):
            raise RuntimeError("sensitive token abc123 should not persist")

        monkeypatch.setattr(executor.audit_service, "finalize_succeeded", fail_finalize)
        result = executor.commit_documents(
            [_energy_document(user, date_value="2026-09-28")],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        runs = db.session.execute(db.select(ImportRun)).scalars().all()
        assert result["committed"] is False
        assert result["rollback"] is True
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].id == result["audit_run_id"]
        assert "abc123" not in runs[0].error_message
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_pending_audit_creation_failure_prevents_domain_mutation(app, user):
    class FailingAuditService(ImportAuditService):
        def record_pending(self, **_kwargs):
            raise RuntimeError("audit unavailable")

    with app.app_context():
        executor = StandardImportExecutor(audit_service=FailingAuditService())

        with pytest.raises(RuntimeError):
            executor.commit_documents(
                [_energy_document(user, date_value="2026-09-29")],
                user_id=user,
                target_type="daily_energy",
                confirmed=True,
            )

        assert db.session.execute(db.select(ImportRun)).scalars().all() == []
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_completed_workout_conflict_creates_blocked_audit_run(app, user):
    with app.app_context():
        plan, version = _seed_plan(user)
        document = _completed_workout_document(user, plan.id, version.id)
        executor = StandardImportExecutor()
        executor.commit_documents(
            [document],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )
        result = executor.commit_documents(
            [document],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )

        runs = db.session.execute(
            db.select(ImportRun).order_by(ImportRun.id)
        ).scalars().all()
        assert result["conflicts"] == 1
        assert runs[-1].status == "blocked"
        assert runs[-1].conflict_count == 1
        assert db.session.execute(db.select(TrainingSession)).scalars().all()[0].user_id == user


def test_preview_and_invalid_token_do_not_create_audit_run(app, client, user):
    login(client)
    preview = _preview(client, {"energia": [{"fecha": "2026-09-05", "calorias_totales": 2400}]})
    assert preview.status_code == 200

    data = _confirm_data(preview)
    data["confirmation_token"] = data["confirmation_token"] + "tampered"
    response = client.post("/imports/standard", data=data)

    assert response.status_code == 200
    assert b"No fue posible" in response.data
    with app.app_context():
        assert db.session.execute(db.select(ImportRun)).scalars().all() == []
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_confirmation_token_from_other_user_does_not_create_audit_run(app, client, user):
    login(client)
    preview = _preview(client, {"energia": [{"fecha": "2026-09-07", "calorias_totales": 2400}]})
    data = _confirm_data(preview)
    with app.app_context():
        second = User(username="audit-token-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    client.post("/logout")
    login(client, "audit-token-second", "second-password")
    response = client.post("/imports/standard", data=data)

    assert response.status_code == 200
    assert b"No fue posible" in response.data
    with app.app_context():
        assert db.session.execute(db.select(ImportRun)).scalars().all() == []
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_import_history_requires_login_and_isolates_users(app, client, user):
    assert client.get("/imports/history").status_code == 302

    with app.app_context():
        second = User(username="audit-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id
        executor = StandardImportExecutor()
        executor.commit_documents(
            [_energy_document(user, date_value="2026-09-06")],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        executor.commit_documents(
            [_energy_document(second_id, date_value="2026-09-06")],
            user_id=second_id,
            target_type="daily_energy",
            confirmed=True,
        )
        own_run = db.session.execute(
            db.select(ImportRun).where(ImportRun.user_id == user)
        ).scalar_one()
        other_run = db.session.execute(
            db.select(ImportRun).where(ImportRun.user_id == second_id)
        ).scalar_one()

    login(client)
    history = client.get("/imports/history")
    detail = client.get(f"/imports/history/{own_run.id}")
    other_detail = client.get(f"/imports/history/{other_run.id}")

    assert history.status_code == 200
    assert b"daily_energy" in history.data
    assert detail.status_code == 200
    assert other_detail.status_code == 404
    assert b"nota privada" not in detail.data
    assert b"total_expenditure_kcal" not in detail.data
    assert b"calorias" not in detail.data.lower()


def test_import_history_paginates(app, client, user):
    with app.app_context():
        executor = StandardImportExecutor()
        for index in range(21):
            executor.commit_documents(
                [_energy_document(user, date_value=f"2026-10-{index + 1:02d}")],
                user_id=user,
                target_type="daily_energy",
                confirmed=True,
            )

    login(client)
    page_one = client.get("/imports/history")
    page_two = client.get("/imports/history?page=2")

    assert page_one.status_code == 200
    assert b"Siguiente" in page_one.data
    assert page_two.status_code == 200
    assert b"Anterior" in page_two.data
