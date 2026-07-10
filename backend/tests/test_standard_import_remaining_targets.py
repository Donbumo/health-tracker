import hashlib

import pytest

from app.extensions import db
from app.models import (
    DailyEnergy,
    MedicalLabReport,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    User,
)
from app.services.importers.standard_import_executor import (
    StandardImportExecutor,
)
from app.services.training_plans import serialize_training_plan
from app.services.validation import JsonSchemaValidationError, validate_json_document


def _energy_doc(
    user_id: int,
    *,
    date_value: str = "2026-08-10",
    total: int = 2420,
    active: int | None = 610,
    notes: str | None = "QA ficticia de energia",
) -> dict:
    data = {
        "date": date_value,
        "source": "qa",
        "total_expenditure_kcal": total,
        "resting_expenditure_kcal": 1810,
        "steps": 8200,
        "distance_meters": 6400,
    }
    if active is not None:
        data["active_expenditure_kcal"] = active
    if notes is not None:
        data["notes"] = notes
    return {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": data,
    }


def _training_doc(
    user_id: int,
    *,
    name: str = "Plan QA Backend",
    description: str | None = "Plan ficticio para QA",
    reps: int = 8,
    duplicate_set_number: bool = False,
) -> dict:
    first_set_number = 1
    second_set_number = 1 if duplicate_set_number else 2
    data = {
        "name": name,
        "weeks": [
            {
                "week_number": 1,
                "name": "Semana QA",
                "days": [
                    {
                        "day_number": 1,
                        "name": "Empuje QA",
                        "exercises": [
                            {
                                "exercise_order": 1,
                                "name": "Press QA",
                                "notes": "Movimiento ficticio",
                                "sets": [
                                    {
                                        "set_number": first_set_number,
                                        "reps_min": reps,
                                        "reps_max": reps + 2,
                                        "rest_seconds": 90,
                                    },
                                    {
                                        "set_number": second_set_number,
                                        "reps": reps,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    if description is not None:
        data["description"] = description
    return {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": data,
    }


def _workout_doc(
    user_id: int,
    *,
    plan_id: int,
    version_id: int,
    performed_at: str = "2026-08-10T18:00:00+00:00",
    weight: int = 60,
) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "training_plan_id": plan_id,
            "training_plan_version_id": version_id,
            "performed_at": performed_at,
            "planned_week_number": 1,
            "planned_day_number": 1,
            "duration_seconds": 3600,
            "average_heart_rate_bpm": 132,
            "calories_burned": 420,
            "notes": "Sesion ficticia QA",
            "exercises": [
                {
                    "exercise_order": 1,
                    "planned_exercise_order": 1,
                    "name": "Press QA",
                    "sets": [
                        {
                            "set_number": 1,
                            "planned_set_number": 1,
                            "weight_kg": weight,
                            "reps": 8,
                            "rir": 2,
                            "rpe": 8,
                            "rest_seconds": 120,
                        }
                    ],
                }
            ],
        },
    }


def _medical_doc(
    user_id: int,
    *,
    date_value: str = "2026-08-10",
    lab: str = "Laboratorio QA",
    glucose: int = 91,
    notes: str | None = "Reporte ficticio QA",
) -> dict:
    document = {
        "schema_version": "1.0",
        "type": "medical_lab",
        "user_id": user_id,
        "source_type": "uploaded",
        "date": date_value,
        "laboratory_name": lab,
        "markers": [
            {
                "name": "Glucosa",
                "code": "GLU",
                "value": glucose,
                "unit": "mg/dL",
                "reference_min": 70,
                "reference_max": 99,
                "status": "normal",
            },
            {
                "name": "Resultado cualitativo QA",
                "value": "negativo",
                "unit": "texto",
                "reference_text": "negativo",
                "status": "normal",
            },
        ],
    }
    if notes is not None:
        document["notes"] = notes
    return document


def _create_second_user() -> int:
    second = User(username="remaining-targets-second", role="user")
    second.set_password("second-password")
    db.session.add(second)
    db.session.commit()
    return second.id


def _insert_training_plan(user_id: int) -> tuple[TrainingPlan, TrainingPlanVersion]:
    executor = StandardImportExecutor()
    executor.commit_documents(
        [_training_doc(user_id)],
        user_id=user_id,
        target_type="training_plan",
        confirmed=True,
    )
    plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
    version = db.session.execute(db.select(TrainingPlanVersion)).scalar_one()
    return plan, version


def test_daily_energy_preview_autodetects_spanish_payload_and_is_read_only(app, user):
    payload = {
        "energia": [
            {
                "fecha": "2026-08-11",
                "calorias_totales": 2440,
                "calorias_activas": 620,
                "pasos": 9300,
                "distancia_km": 7.1,
                "campo_desconocido": "ignorado",
            }
        ]
    }

    with app.app_context():
        result = StandardImportExecutor().preview_payload(payload, user_id=user)

        document = result["documents"][0]
        assert result["read_only"] is True
        assert result["target_type"] == "daily_energy"
        assert result["plan"]["inserts"] == 1
        assert document["data"]["distance_meters"] == 7100
        validate_json_document(document, "daily_energy")
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_daily_energy_commit_update_batch_invalid_and_user_isolation(app, user):
    with app.app_context():
        second_id = _create_second_user()
        executor = StandardImportExecutor()
        original = _energy_doc(user)
        partial = _energy_doc(user, total=2510, active=None, notes=None)
        invalid = _energy_doc(user)
        del invalid["data"]["date"]
        foreign_user = _energy_doc(second_id, date_value="2026-08-12")

        first = executor.commit_documents(
            [original],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        repeated = executor.commit_documents(
            [original],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        updated = executor.commit_documents(
            [partial],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        mixed = executor.commit_documents(
            [_energy_doc(user, date_value="2026-08-13"), invalid],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        rejected_foreign = executor.commit_documents(
            [foreign_user],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert first["inserts"] == 1
        assert repeated["skips"] == 1
        assert updated["updates"] == 1
        assert int(record.total_calories) == 2510
        assert int(record.active_calories) == 610
        assert record.notes == "QA ficticia de energia"
        assert mixed["committed"] is False
        assert mixed["invalid"] == 1
        assert rejected_foreign["invalid"] == 1
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == [record]


def test_training_plan_preview_parent_paths_and_confirmed_versioning(app, user):
    payload = {
        "plan": {
            "nombre": "Plan QA Path",
            "descripcion": "Version inicial",
            "semanas": [
                {
                    "semana": 1,
                    "dias": [
                        {
                            "dia": 1,
                            "nombre": "Torso",
                            "ejercicios": [
                                {
                                    "orden": 1,
                                    "nombre": "Remo QA",
                                    "series": [
                                        {"serie": 1, "reps_min": 8, "reps_max": 10},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }

    with app.app_context():
        executor = StandardImportExecutor()
        preview = executor.preview_payload(payload, user_id=user)
        document = preview["documents"][0]
        assert preview["target_type"] == "training_plan"
        assert document["data"]["name"] == "Plan QA Path"
        validate_json_document(document, "training_plan")

        first = executor.commit_documents(
            [document],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
        )
        repeated = executor.commit_documents(
            [document],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
        )
        updated_document = _training_doc(
            user,
            name="Plan QA Path",
            description=None,
            reps=10,
        )
        updated = executor.commit_documents(
            [updated_document],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
        )

        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        versions = db.session.execute(
            db.select(TrainingPlanVersion).order_by(TrainingPlanVersion.version_number)
        ).scalars().all()
        assert first["inserts"] == 1
        assert repeated["skips"] == 1
        assert updated["updates"] == 1
        assert plan.active_version_number == 2
        assert plan.description == "Version inicial"
        assert [version.version_number for version in versions] == [1, 2]
        assert versions[0].sha256 == hashlib.sha256(
            serialize_training_plan(versions[0].content)
        ).hexdigest()
        assert versions[0].sha256 != versions[1].sha256


def test_training_plan_invalid_order_rolls_back_and_user_isolation(app, user):
    with app.app_context():
        second_id = _create_second_user()
        executor = StandardImportExecutor()
        duplicate_order = _training_doc(user, duplicate_set_number=True)
        foreign_user = _training_doc(second_id, name="Plan usuario ajeno")

        ordering_result = executor.commit_documents(
            [duplicate_order],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
        )
        foreign_result = executor.commit_documents(
            [foreign_user],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
        )
        second_result = executor.commit_documents(
            [_training_doc(second_id, name="Plan usuario ajeno")],
            user_id=second_id,
            target_type="training_plan",
            confirmed=True,
        )

        assert ordering_result["rollback"] is True
        assert "Set numbers must be unique" in ordering_result["errors"][0]
        assert foreign_result["invalid"] == 1
        assert second_result["inserts"] == 1
        plans = db.session.execute(db.select(TrainingPlan)).scalars().all()
        assert [(plan.user_id, plan.name) for plan in plans] == [
            (second_id, "Plan usuario ajeno")
        ]


def test_completed_workout_requires_owned_consistent_plan_and_preserves_extended_fields(app, user):
    with app.app_context():
        second_id = _create_second_user()
        plan, version = _insert_training_plan(user)
        other_executor = StandardImportExecutor()
        other_executor.commit_documents(
            [_training_doc(second_id, name="Plan ajeno")],
            user_id=second_id,
            target_type="training_plan",
            confirmed=True,
        )
        other_version = db.session.execute(
            db.select(TrainingPlanVersion).where(TrainingPlanVersion.user_id == second_id)
        ).scalar_one()
        executor = StandardImportExecutor()
        valid = _workout_doc(user, plan_id=plan.id, version_id=version.id)
        foreign_version = _workout_doc(
            user,
            plan_id=other_version.training_plan_id,
            version_id=other_version.id,
            performed_at="2026-08-11T18:00:00+00:00",
        )
        inconsistent = _workout_doc(
            user,
            plan_id=plan.id + 999,
            version_id=version.id,
            performed_at="2026-08-12T18:00:00+00:00",
        )

        first = executor.commit_documents(
            [valid],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )
        repeated = executor.commit_documents(
            [valid],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )
        rejected_foreign = executor.commit_documents(
            [foreign_version],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )
        rejected_inconsistent = executor.commit_documents(
            [inconsistent],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )

        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        training_set = session.exercises[0].sets[0]
        assert first["inserts"] == 1
        assert repeated["conflicts"] == 1
        assert rejected_foreign["rollback"] is True
        assert rejected_inconsistent["rollback"] is True
        assert session.user_id == user
        assert session.duration_seconds == 3600
        assert session.average_heart_rate_bpm == 132
        assert int(session.calories_burned) == 420
        assert float(training_set.rpe) == 8.0
        assert float(training_set.rir) == 2.0
        assert training_set.rest_seconds == 120


def test_completed_workout_batch_rolls_back_after_flush(app, user, monkeypatch):
    with app.app_context():
        plan, version = _insert_training_plan(user)
        documents = [
            _workout_doc(
                user,
                plan_id=plan.id,
                version_id=version.id,
                performed_at="2026-08-13T18:00:00+00:00",
            ),
            _workout_doc(
                user,
                plan_id=plan.id,
                version_id=version.id,
                performed_at="2026-08-14T18:00:00+00:00",
            ),
        ]
        executor = StandardImportExecutor()
        original_apply = executor._apply_document
        calls = {"count": 0}

        def fail_after_first(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated completed workout write failure")
            return original_apply(*args, **kwargs)

        monkeypatch.setattr(executor, "_apply_document", fail_after_first)

        result = executor.commit_documents(
            documents,
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )

        assert result["committed"] is False
        assert result["rollback"] is True
        assert db.session.execute(db.select(TrainingSession)).scalars().all() == []


def test_completed_workout_generator_does_not_invent_plan_references(app, user):
    payload = {
        "sesiones": [
            {
                "fecha": "2026-08-15",
                "ejercicios": [
                    {
                        "nombre": "Press QA",
                        "series": [{"peso": 55, "reps": 8}],
                    }
                ],
            }
        ]
    }

    with app.app_context():
        result = StandardImportExecutor().preview_payload(
            payload,
            user_id=user,
            requested_type="completed_workout",
        )
        document = result["documents"][0]
        data = document["data"]
        assert "training_plan_id" not in data
        assert "training_plan_version_id" not in data
        assert result["plan"]["invalid"] == 1


def test_medical_lab_commit_update_replaces_markers_and_preserves_absent_notes(app, user):
    with app.app_context():
        second_id = _create_second_user()
        executor = StandardImportExecutor()
        original = _medical_doc(user)
        partial = _medical_doc(user, glucose=96, notes=None)
        partial["markers"] = [partial["markers"][0]]
        invalid_missing_date = _medical_doc(user)
        del invalid_missing_date["date"]
        invalid_marker = _medical_doc(user, date_value="2026-08-11")
        del invalid_marker["markers"][0]["unit"]
        foreign_user = _medical_doc(second_id, date_value="2026-08-12")

        first = executor.commit_documents(
            [original],
            user_id=user,
            target_type="medical_lab",
            confirmed=True,
        )
        repeated = executor.commit_documents(
            [original],
            user_id=user,
            target_type="medical_lab",
            confirmed=True,
        )
        updated = executor.commit_documents(
            [partial],
            user_id=user,
            target_type="medical_lab",
            confirmed=True,
        )
        mixed_invalid = executor.commit_documents(
            [_medical_doc(user, date_value="2026-08-13"), invalid_missing_date],
            user_id=user,
            target_type="medical_lab",
            confirmed=True,
        )
        invalid_marker_result = executor.commit_documents(
            [invalid_marker],
            user_id=user,
            target_type="medical_lab",
            confirmed=True,
        )
        foreign_result = executor.commit_documents(
            [foreign_user],
            user_id=user,
            target_type="medical_lab",
            confirmed=True,
        )

        report = db.session.execute(db.select(MedicalLabReport)).scalar_one()
        assert first["inserts"] == 1
        assert repeated["skips"] == 1
        assert updated["updates"] == 1
        assert report.notes == "Reporte ficticio QA"
        assert len(report.results) == 1
        assert float(report.results[0].value) == 96.0
        assert mixed_invalid["committed"] is False
        assert mixed_invalid["invalid"] == 1
        assert invalid_marker_result["invalid"] == 1
        assert foreign_result["invalid"] == 1


def test_medical_lab_preview_autodetects_nested_markers_and_remains_read_only(app, user):
    payload = {
        "reporte": {
            "fecha": "2026-08-16",
            "laboratorio": "Laboratorio Preview QA",
            "marcadores": [
                {
                    "nombre": "Glucosa",
                    "valor": 89,
                    "unidad": "mg/dL",
                    "estado": "normal",
                }
            ],
        }
    }

    with app.app_context():
        result = StandardImportExecutor().preview_payload(payload, user_id=user)
        document = result["documents"][0]

        assert result["target_type"] == "medical_lab"
        assert result["read_only"] is True
        assert document["date"] == "2026-08-16"
        validate_json_document(document, "medical_lab")
        assert db.session.execute(db.select(MedicalLabReport)).scalars().all() == []


@pytest.mark.parametrize(
    ("target_type", "schema_name", "document_factory"),
    [
        ("daily_energy", "daily_energy", _energy_doc),
        ("training_plan", "training_plan", _training_doc),
        ("medical_lab", "medical_lab", _medical_doc),
    ],
)
def test_remaining_targets_reject_document_user_id_from_another_account(
    app,
    user,
    target_type,
    schema_name,
    document_factory,
):
    with app.app_context():
        second_id = _create_second_user()
        document = document_factory(second_id)
        validate_json_document(document, schema_name)

        result = StandardImportExecutor().commit_documents(
            [document],
            user_id=user,
            target_type=target_type,
            confirmed=True,
        )

        assert result["committed"] is False
        assert result["invalid"] == 1
        assert any("user_id" in error for error in result["errors"])


def test_completed_workout_schema_rejects_missing_required_plan_references(app, user):
    with app.app_context():
        document = _workout_doc(user, plan_id=1, version_id=1)
        del document["data"]["training_plan_id"]

        with pytest.raises(JsonSchemaValidationError):
            validate_json_document(document, "completed_workout")
