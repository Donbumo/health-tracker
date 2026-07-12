import io
import json
import re
from html import unescape

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    FoodProduct,
    ImportRun,
    MedicalLabReport,
    NutritionItem,
    RecipeIngredient,
    Recipe,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    UploadedFile,
    User,
    WeighIn,
)
from app.services.account_restore import AccountRestoreError, AccountRestoreService
from app.services.exporters.user_data import build_user_data_document
from app.services.importers.standard_import_executor import StandardImportExecutor
from tests.conftest import login


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


def _full_account_payload(user_id: int) -> dict:
    executor = StandardImportExecutor()
    food = {
        "schema_version": "1.0",
        "type": "food_product",
        "user_id": user_id,
        "source_type": "uploaded",
        "name": "Avena ficticia",
        "brand": "QA",
        "source": "qa",
        "calories_per_100g": 389,
        "protein_g_per_100g": 16.9,
    }
    recipe = {
        "schema_version": "1.0",
        "type": "recipe",
        "user_id": user_id,
        "source_type": "uploaded",
        "name": "Desayuno ficticio",
        "servings": 1,
        "source": "qa",
        "ingredients": [
            {
                "food_product_name": "Avena ficticia",
                "food_product_brand": "QA",
                "quantity_g": 80,
            }
        ],
    }
    weigh_in = {
        "schema_version": "1.0",
        "record_type": "weigh_in",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {
            "recorded_at": "2026-07-10T07:00:00+00:00",
            "weight_kg": 74.5,
            "source": "qa",
        },
    }
    energy = {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "date": "2026-07-10",
            "source": "qa",
            "total_expenditure_kcal": 2400,
            "active_expenditure_kcal": 600,
            "steps": 8000,
        },
    }
    nutrition = {
        "schema_version": "1.0",
        "record_type": "daily_nutrition",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "date": "2026-07-10",
            "source": "qa",
            "calories_kcal": 2100,
            "protein_g": 140,
            "fat_g": 70,
            "net_carbs_g": 180,
            "meals": [
                {
                    "meal_type": "breakfast",
                    "items": [
                        {
                            "name": "Avena cocida ficticia",
                            "quantity": 1,
                            "unit": "bowl",
                            "calories_kcal": 350,
                        }
                    ],
                }
            ],
        },
    }
    plan = {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": "Rutina roundtrip ficticia",
            "description": "Plan QA",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Fuerza",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Sentadilla ficticia",
                                    "sets": [{"set_number": 1, "reps": 5}],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }
    lab = {
        "schema_version": "1.0",
        "type": "medical_lab",
        "user_id": user_id,
        "source_type": "uploaded",
        "date": "2026-07-10",
        "laboratory_name": "Laboratorio QA",
        "source": "qa",
        "markers": [
            {"name": "Glucosa ficticia", "value": 88, "unit": "mg/dL", "status": "normal"}
        ],
    }

    for document, target in (
        (food, "food_product"),
        (recipe, "recipe"),
        (weigh_in, "weigh_in"),
        (energy, "daily_energy"),
        (nutrition, "daily_nutrition"),
        (plan, "training_plan"),
        (lab, "medical_lab"),
    ):
        executor.commit_documents([document], user_id=user_id, target_type=target, confirmed=True)

    training_plan = db.session.execute(
        db.select(TrainingPlan).where(TrainingPlan.user_id == user_id)
    ).scalar_one()
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(TrainingPlanVersion.training_plan_id == training_plan.id)
    ).scalar_one()
    workout = {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {
            "training_plan_id": training_plan.id,
            "training_plan_version_id": version.id,
            "performed_at": "2026-07-10T08:00:00+00:00",
            "planned_week_number": 1,
            "planned_day_number": 1,
            "duration_seconds": 1800,
            "exercises": [
                {
                    "exercise_order": 1,
                    "planned_exercise_order": 1,
                    "name": "Sentadilla ficticia",
                    "sets": [
                        {
                            "set_number": 1,
                            "planned_set_number": 1,
                            "weight_kg": 100,
                            "reps": 5,
                            "rpe": 8,
                            "rest_seconds": 120,
                        }
                    ],
                }
            ],
        },
    }
    executor.commit_documents([workout], user_id=user_id, target_type="completed_workout", confirmed=True)

    user = db.session.get(User, user_id)
    return build_user_data_document(user, user_id)


def _complete_account_payload(user_id: int) -> dict:
    executor = StandardImportExecutor()
    products = [
        ("Avena ficticia", "QA", 389, 16.9),
        ("Yogur ficticio", "QA", 65, 5.4),
        ("Nuez ficticia", "QA", 607, 20.0),
    ]
    for name, brand, calories, protein in products:
        executor.commit_documents(
            [
                {
                    "schema_version": "1.0",
                    "type": "food_product",
                    "user_id": user_id,
                    "source_type": "uploaded",
                    "name": name,
                    "brand": brand,
                    "source": "qa",
                    "calories_per_100g": calories,
                    "protein_g_per_100g": protein,
                }
            ],
            user_id=user_id,
            target_type="food_product",
            confirmed=True,
        )

    for recipe_name, ingredient_names in (
        ("Bowl ficticio", ["Avena ficticia", "Yogur ficticio"]),
        ("Snack ficticio", ["Nuez ficticia", "Yogur ficticio"]),
    ):
        executor.commit_documents(
            [
                {
                    "schema_version": "1.0",
                    "type": "recipe",
                    "user_id": user_id,
                    "source_type": "uploaded",
                    "name": recipe_name,
                    "servings": 2,
                    "source": "qa",
                    "ingredients": [
                        {
                            "food_product_name": item_name,
                            "food_product_brand": "QA",
                            "quantity_g": 50 + index * 25,
                            "sort_order": index,
                        }
                        for index, item_name in enumerate(ingredient_names, start=1)
                    ],
                }
            ],
            user_id=user_id,
            target_type="recipe",
            confirmed=True,
        )

    for index, weight in enumerate((74.5, 74.1), start=10):
        executor.commit_documents(
            [
                {
                    "schema_version": "1.0",
                    "record_type": "weigh_in",
                    "user_id": user_id,
                    "source_type": "manual_generated",
                    "data": {
                        "recorded_at": f"2026-07-{index}T07:00:00+00:00",
                        "weight_kg": weight,
                        "source": "qa",
                    },
                }
            ],
            user_id=user_id,
            target_type="weigh_in",
            confirmed=True,
        )
        executor.commit_documents(
            [
                {
                    "schema_version": "1.0",
                    "record_type": "daily_energy",
                    "user_id": user_id,
                    "source_type": "uploaded",
                    "data": {
                        "date": f"2026-07-{index}",
                        "source": "qa",
                        "total_expenditure_kcal": 2400 + index,
                        "active_expenditure_kcal": 500 + index,
                        "steps": 7000 + index,
                    },
                }
            ],
            user_id=user_id,
            target_type="daily_energy",
            confirmed=True,
        )
        executor.commit_documents(
            [
                {
                    "schema_version": "1.0",
                    "record_type": "daily_nutrition",
                    "user_id": user_id,
                    "source_type": "uploaded",
                    "data": {
                        "date": f"2026-07-{index}",
                        "source": "qa",
                        "calories_kcal": 2100 + index,
                        "protein_g": 140,
                        "meals": [
                            {
                                "meal_type": "breakfast",
                                "sort_order": 1,
                                "items": [
                                    {
                                        "name": f"Comida ficticia {index}",
                                        "quantity": 1,
                                        "unit": "plate",
                                        "sort_order": 1,
                                        "calories_kcal": 350 + index,
                                        "protein_g": 30,
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
            user_id=user_id,
            target_type="daily_nutrition",
            confirmed=True,
        )

    first_plan = {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": "Plan roundtrip completo",
            "description": "v1",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Fuerza A",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Sentadilla ficticia",
                                    "sets": [{"set_number": 1, "reps": 5}],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }
    second_plan = json.loads(json.dumps(first_plan))
    second_plan["data"]["description"] = "v2"
    second_plan["data"]["weeks"][0]["days"][0]["exercises"][0]["sets"].append(
        {"set_number": 2, "reps": 5}
    )
    executor.commit_documents([first_plan], user_id=user_id, target_type="training_plan", confirmed=True)
    executor.commit_documents([second_plan], user_id=user_id, target_type="training_plan", confirmed=True)

    plan = db.session.execute(
        db.select(TrainingPlan).where(
            TrainingPlan.user_id == user_id,
            TrainingPlan.name == "Plan roundtrip completo",
        )
    ).scalar_one()
    versions = {version.version_number: version for version in plan.versions}
    for version_number, performed_date, set_count in (
        (1, "2026-07-10T08:00:00+00:00", 1),
        (2, "2026-07-11T08:00:00+00:00", 2),
    ):
        executor.commit_documents(
            [
                {
                    "schema_version": "1.0",
                    "record_type": "completed_workout",
                    "user_id": user_id,
                    "source_type": "manual_generated",
                    "data": {
                        "training_plan_id": plan.id,
                        "training_plan_version_id": versions[version_number].id,
                        "performed_at": performed_date,
                        "planned_week_number": 1,
                        "planned_day_number": 1,
                        "duration_seconds": 1800 + version_number,
                        "average_heart_rate_bpm": 120 + version_number,
                        "calories_burned": 300 + version_number,
                        "exercises": [
                            {
                                "exercise_order": 1,
                                "planned_exercise_order": 1,
                                "name": "Sentadilla ficticia",
                                "sets": [
                                    {
                                        "set_number": set_number,
                                        "planned_set_number": set_number,
                                        "weight_kg": 100 + set_number,
                                        "reps": 5,
                                        "rir": 2,
                                        "rpe": 8,
                                        "rest_seconds": 120,
                                    }
                                    for set_number in range(1, set_count + 1)
                                ],
                            }
                        ],
                    },
                }
            ],
            user_id=user_id,
            target_type="completed_workout",
            confirmed=True,
        )

    executor.commit_documents(
        [
            {
                "schema_version": "1.0",
                "type": "medical_lab",
                "user_id": user_id,
                "source_type": "uploaded",
                "date": "2026-07-10",
                "laboratory_name": "Laboratorio QA completo",
                "source": "qa",
                "markers": [
                    {"name": "Glucosa ficticia", "value": 88, "unit": "mg/dL", "status": "normal"},
                    {"name": "Resultado texto ficticio", "value": "negativo", "unit": "texto", "status": "unknown"},
                ],
            }
        ],
        user_id=user_id,
        target_type="medical_lab",
        confirmed=True,
    )

    return build_user_data_document(db.session.get(User, user_id), user_id)


def _complete_roundtrip_payload(user_id: int) -> dict:
    """Full fictitious export fixture for account restore round-trip tests."""
    payload = _complete_account_payload(user_id)
    assert len(payload["data"]["weigh_ins"]) == 2
    assert len(payload["data"]["daily_energy"]) == 2
    assert len(payload["data"]["daily_nutrition"]) == 2
    assert len(payload["data"]["food_products"]) == 3
    assert len(payload["data"]["recipes"]) == 2
    assert len(payload["data"]["medical_lab_reports"]) == 1
    assert len(payload["data"]["training_plans"]) == 1
    assert len(payload["data"]["training_plans"][0]["versions"]) == 2
    assert len(payload["data"]["training_sessions"]) == 2
    assert "uploads" in payload["data"]
    assert "daily_balances" in payload["data"]
    return payload


def _make_user(username: str, email: str) -> User:
    user = User(username=username, email=email, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def _restore_payload_to_user(payload: dict, user_id: int) -> dict:
    service = AccountRestoreService()
    preview = service.preview(payload, user_id=user_id)
    return service.commit(
        payload,
        user_id=user_id,
        confirmation_token=preview["confirmation_token"],
    )


def _domain_counts(user_id: int) -> dict[str, int]:
    return {
        "weigh_ins": db.session.execute(
            db.select(db.func.count(WeighIn.id)).where(WeighIn.user_id == user_id)
        ).scalar_one(),
        "daily_energy": db.session.execute(
            db.select(db.func.count(DailyEnergy.id)).where(DailyEnergy.user_id == user_id)
        ).scalar_one(),
        "daily_nutrition": db.session.execute(
            db.select(db.func.count(DailyNutrition.id)).where(DailyNutrition.user_id == user_id)
        ).scalar_one(),
        "food_products": db.session.execute(
            db.select(db.func.count(FoodProduct.id)).where(FoodProduct.user_id == user_id)
        ).scalar_one(),
        "recipes": db.session.execute(
            db.select(db.func.count(Recipe.id)).where(Recipe.user_id == user_id)
        ).scalar_one(),
        "recipe_ingredients": db.session.execute(
            db.select(db.func.count(RecipeIngredient.id)).where(RecipeIngredient.user_id == user_id)
        ).scalar_one(),
        "medical_lab_reports": db.session.execute(
            db.select(db.func.count(MedicalLabReport.id)).where(MedicalLabReport.user_id == user_id)
        ).scalar_one(),
        "training_plans": db.session.execute(
            db.select(db.func.count(TrainingPlan.id)).where(TrainingPlan.user_id == user_id)
        ).scalar_one(),
        "training_plan_versions": db.session.execute(
            db.select(db.func.count(TrainingPlanVersion.id)).where(
                TrainingPlanVersion.user_id == user_id
            )
        ).scalar_one(),
        "training_sessions": db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(TrainingSession.user_id == user_id)
        ).scalar_one(),
        "training_sets": db.session.execute(
            db.select(db.func.count(TrainingSet.id)).where(TrainingSet.user_id == user_id)
        ).scalar_one(),
        "uploads": db.session.execute(
            db.select(db.func.count(UploadedFile.id)).where(UploadedFile.user_id == user_id)
        ).scalar_one(),
    }


SEMANTICALLY_IGNORED_EXPORT_FIELDS = {
    "id",
    "user",
    "user_id",
    "exported_at",
    "created_at",
    "updated_at",
    "source_file_id",
    "created_by_user_id",
    "change_reason",
    "sha256",
}


def _semantic_user_data_export(document: dict) -> dict:
    """Normalize account exports while preserving domain values and semantic refs."""
    normalized = json.loads(json.dumps(document, sort_keys=True))
    training_plan_names = {
        plan["id"]: plan["name"]
        for plan in normalized["data"].get("training_plans", [])
        if "id" in plan
    }
    version_names = {}
    for plan in normalized["data"].get("training_plans", []):
        for version in plan.get("versions", []):
            if "id" in version:
                version_names[version["id"]] = (plan["name"], version["version_number"])
    for session in normalized["data"].get("training_sessions", []):
        data = session.get("data", {})
        data["training_plan_ref"] = training_plan_names.get(data.get("training_plan_id"))
        data["training_plan_version_ref"] = version_names.get(data.get("training_plan_version_id"))
        data.pop("training_plan_id", None)
        data.pop("training_plan_version_id", None)

    def scrub(value):
        if isinstance(value, list):
            return sorted(
                (scrub(item) for item in value),
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                if key in SEMANTICALLY_IGNORED_EXPORT_FIELDS:
                    continue
                clean[key] = scrub(item)
            return clean
        return value

    return scrub(normalized)


def _semantic_export(document: dict) -> dict:
    return _semantic_user_data_export(document)


def _restore_domain_matrix(user_id: int) -> dict[str, str]:
    counts = _domain_counts(user_id)
    return {
        "weigh_ins": f"{counts['weigh_ins']} restored",
        "daily_energy": f"{counts['daily_energy']} restored",
        "daily_nutrition": f"{counts['daily_nutrition']} restored",
        "food_products": f"{counts['food_products']} restored",
        "recipes": f"{counts['recipes']} restored",
        "recipe_bundle": "not persisted as bundle model",
        "medical_lab_reports": f"{counts['medical_lab_reports']} restored",
        "training_plans": f"{counts['training_plans']} plan / {counts['training_plan_versions']} versions",
        "training_sessions": f"{counts['training_sessions']} sessions / {counts['training_sets']} sets",
        "uploads": f"{counts['uploads']} binary rows; export metadata unsupported",
        "daily_balances": "derived, not persisted by restore",
    }


def test_account_restore_roundtrip_remaps_ids_and_preserves_source_user(app, user):
    with app.app_context():
        source = db.session.get(User, user)
        source.email = "source@example.test"
        payload = _full_account_payload(user)
        target = _make_user("restore-target", "target@example.test")
        target_id = target.id
        db.session.commit()

        preview = AccountRestoreService().preview(payload, user_id=target_id)
        result = AccountRestoreService().commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

        assert result["committed"] is True
        assert result["rollback"] is False
        assert result["inserts"] >= 8
        assert db.session.execute(
            db.select(WeighIn).where(WeighIn.user_id == target_id)
        ).scalar_one()
        assert db.session.execute(
            db.select(DailyEnergy).where(DailyEnergy.user_id == target_id)
        ).scalar_one()
        assert db.session.execute(
            db.select(DailyNutrition).where(DailyNutrition.user_id == target_id)
        ).scalar_one()
        assert db.session.execute(
            db.select(FoodProduct).where(FoodProduct.user_id == target_id)
        ).scalar_one()
        assert db.session.execute(
            db.select(Recipe).where(Recipe.user_id == target_id)
        ).scalar_one()
        assert db.session.execute(
            db.select(MedicalLabReport).where(MedicalLabReport.user_id == target_id)
        ).scalar_one()
        restored_session = db.session.execute(
            db.select(TrainingSession).where(TrainingSession.user_id == target_id)
        ).scalar_one()
        assert restored_session.training_plan.user_id == target_id
        assert restored_session.training_plan_version.user_id == target_id
        assert db.session.get(User, target_id).email == "target@example.test"
        assert db.session.execute(
            db.select(TrainingSession).where(TrainingSession.user_id == user)
        ).scalar_one()


def test_account_restore_repeat_is_idempotent_and_audited(app, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("restore-idempotent", "restore-idempotent@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        first_preview = service.preview(payload, user_id=target_id)
        first = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=first_preview["confirmation_token"],
        )
        second_preview = service.preview(payload, user_id=target_id)
        second = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=second_preview["confirmation_token"],
        )

        assert first["committed"] is True
        assert second["committed"] is True
        assert second["skips"] >= 8
        assert db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(TrainingSession.user_id == target_id)
        ).scalar_one() == 1
        runs = db.session.execute(
            db.select(ImportRun).where(
                ImportRun.user_id == target_id,
                ImportRun.target_type == "user_data_restore",
            )
        ).scalars().all()
        assert len(runs) == 2
        assert all(run.status == "succeeded" for run in runs)


def test_account_restore_pending_is_persisted_before_domain_mutation(app, user, monkeypatch):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("restore-pending", "restore-pending@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        observed = {"pending": False}

        def fail_after_pending(*args, **kwargs):
            observed["pending"] = db.session.execute(
                db.select(ImportRun).where(
                    ImportRun.user_id == target_id,
                    ImportRun.target_type == "user_data_restore",
                    ImportRun.status == "pending",
                )
            ).scalar_one_or_none() is not None
            raise RuntimeError("forced restore failure")

        monkeypatch.setattr(service, "_apply_payload", fail_after_pending)
        result = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

        run = db.session.get(ImportRun, result["audit_run_id"])
        assert observed["pending"] is True
        assert result["committed"] is False
        assert result["rollback"] is True
        assert run.status == "failed"
        assert db.session.execute(
            db.select(db.func.count(WeighIn.id)).where(WeighIn.user_id == target_id)
        ).scalar_one() == 0


def test_account_restore_final_audit_failure_rolls_back_and_marks_failed(
    app,
    user,
    monkeypatch,
):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("restore-final-fail", "restore-final-fail@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)

        def fail_finalize(*args, **kwargs):
            raise RuntimeError("audit finalize unavailable")

        monkeypatch.setattr(service.audit_service, "finalize_succeeded", fail_finalize)
        result = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

        run = db.session.get(ImportRun, result["audit_run_id"])
        assert result["committed"] is False
        assert result["rollback"] is True
        assert run.status == "failed"
        assert db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(
                TrainingSession.user_id == target_id
            )
        ).scalar_one() == 0


def test_account_restore_initial_audit_failure_prevents_domain_mutation(
    app,
    user,
    monkeypatch,
):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("restore-audit-create-fail", "restore-audit-create-fail@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        observed = {"mutated": False}

        def fail_record_pending(**kwargs):
            raise RuntimeError("audit unavailable")

        def observe_mutation(*args, **kwargs):
            observed["mutated"] = True
            return {}

        monkeypatch.setattr(service.audit_service, "record_pending", fail_record_pending)
        monkeypatch.setattr(service, "_apply_payload", observe_mutation)

        try:
            service.commit(
                payload,
                user_id=target_id,
                confirmation_token=preview["confirmation_token"],
            )
        except RuntimeError as error:
            assert "audit unavailable" in str(error)
        else:
            raise AssertionError("audit creation failure should propagate")

        assert observed["mutated"] is False
        assert db.session.execute(
            db.select(db.func.count(ImportRun.id)).where(ImportRun.user_id == target_id)
        ).scalar_one() == 0
        assert db.session.execute(
            db.select(db.func.count(FoodProduct.id)).where(FoodProduct.user_id == target_id)
        ).scalar_one() == 0


def test_complete_export_restore_export_semantic_roundtrip(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("semantic-target", "semantic-target@example.test")
        target_id = target.id
        db.session.commit()

        result = _restore_payload_to_user(payload, target_id)
        restored_export = build_user_data_document(db.session.get(User, target_id), target_id)

        assert result["committed"] is True
        assert _semantic_user_data_export(restored_export) == _semantic_user_data_export(payload)


def test_repeated_restore_is_idempotent(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("idempotent-target", "idempotent-target@example.test")
        target_id = target.id
        db.session.commit()

        first = _restore_payload_to_user(payload, target_id)
        counts_after_first = _domain_counts(target_id)
        second = _restore_payload_to_user(payload, target_id)
        counts_after_second = _domain_counts(target_id)

        assert first["committed"] is True
        assert second["committed"] is True
        assert second["inserts"] == 0
        assert second["updates"] == 0
        assert second["skips"] >= 15
        assert counts_after_second == counts_after_first


def test_source_user_remains_unchanged(app, user):
    with app.app_context():
        source = db.session.get(User, user)
        source.email = "source-remains@example.test"
        payload = _complete_roundtrip_payload(user)
        source_counts_before = _domain_counts(user)
        target = _make_user("source-unchanged-target", "source-unchanged-target@example.test")
        target_id = target.id
        db.session.commit()

        _restore_payload_to_user(payload, target_id)

        assert db.session.get(User, user).email == "source-remains@example.test"
        assert _domain_counts(user) == source_counts_before


def test_destination_ownership_is_rewritten(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("ownership-target", "ownership-target@example.test")
        target_id = target.id
        db.session.commit()

        _restore_payload_to_user(payload, target_id)

        for model in (
            WeighIn,
            DailyEnergy,
            DailyNutrition,
            FoodProduct,
            Recipe,
            RecipeIngredient,
            MedicalLabReport,
            TrainingPlan,
            TrainingPlanVersion,
            TrainingSession,
            TrainingSessionExercise,
            TrainingSet,
        ):
            owner_ids = {
                row.user_id
                for row in db.session.execute(
                    db.select(model).where(model.user_id == target_id)
                ).scalars()
            }
            assert owner_ids == {target_id}
        assert db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(
                TrainingSession.user_id == user
            )
        ).scalar_one() == 2


def test_recipe_product_references_are_remapped(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        source_product_ids = {
            product.id
            for product in db.session.execute(
                db.select(FoodProduct).where(FoodProduct.user_id == user)
            ).scalars()
        }
        target = _make_user("recipe-remap-target", "recipe-remap@example.test")
        target_id = target.id
        db.session.commit()

        _restore_payload_to_user(payload, target_id)

        ingredients = db.session.execute(
            db.select(RecipeIngredient).where(RecipeIngredient.user_id == target_id)
        ).scalars().all()
        assert len(ingredients) == 4
        assert {ingredient.food_product.user_id for ingredient in ingredients} == {target_id}
        assert {ingredient.food_product_id for ingredient in ingredients}.isdisjoint(source_product_ids)
        assert {ingredient.name_snapshot for ingredient in ingredients} == {
            "Avena ficticia",
            "Yogur ficticio",
            "Nuez ficticia",
        }


def test_broken_recipe_reference_blocks_restore(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        payload["data"]["food_products"] = []
        payload["data"]["recipes"][0]["ingredients"][0]["food_product_name"] = (
            "Producto roto ficticio"
        )
        target = _make_user("broken-recipe-target", "broken-recipe@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        result = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

        assert preview["valid"] is False
        assert result["committed"] is False
        assert result["rollback"] is False
        assert result["invalid"] >= 1
        assert _domain_counts(target_id)["food_products"] == 0
        assert db.session.get(ImportRun, result["audit_run_id"]).status == "blocked"


def test_recipe_failure_rolls_back_products(app, user, monkeypatch):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("recipe-rollback-target", "recipe-rollback@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)

        def fail_recipe(*args, **kwargs):
            raise RuntimeError("forced recipe persistence failure")

        monkeypatch.setattr(service, "_apply_recipe", fail_recipe)
        result = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

        assert result["committed"] is False
        assert result["rollback"] is True
        assert _domain_counts(target_id)["food_products"] == 0
        assert _domain_counts(target_id)["recipes"] == 0
        assert db.session.get(ImportRun, result["audit_run_id"]).status == "failed"


def test_training_versions_and_active_version_are_preserved(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("versions-target", "versions@example.test")
        target_id = target.id
        db.session.commit()

        _restore_payload_to_user(payload, target_id)

        plan = db.session.execute(
            db.select(TrainingPlan).where(TrainingPlan.user_id == target_id)
        ).scalar_one()
        versions = sorted(plan.versions, key=lambda version: version.version_number)
        assert plan.active_version_number == 2
        assert [version.version_number for version in versions] == [1, 2]
        assert [version.version_number == plan.active_version_number for version in versions] == [
            False,
            True,
        ]
        assert versions[0].content["data"]["description"] == "v1"
        assert versions[1].content["data"]["description"] == "v2"
        assert len(versions[1].content["data"]["weeks"][0]["days"][0]["exercises"][0]["sets"]) == 2


def test_sessions_remap_to_correct_restored_versions(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("session-version-target", "session-version@example.test")
        target_id = target.id
        db.session.commit()

        _restore_payload_to_user(payload, target_id)

        sessions = db.session.execute(
            db.select(TrainingSession)
            .where(TrainingSession.user_id == target_id)
            .order_by(TrainingSession.performed_at)
        ).scalars().all()
        assert len(sessions) == 2
        assert [session.training_plan_version.version_number for session in sessions] == [1, 2]
        assert [len(session.exercises[0].sets) for session in sessions] == [1, 2]
        assert {session.training_plan.user_id for session in sessions} == {target_id}
        assert {session.training_plan_version.user_id for session in sessions} == {target_id}


def test_restored_plan_can_start_new_session_and_update_progress(app, client, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("new-session-target", "new-session@example.test")
        target_id = target.id
        db.session.commit()

        _restore_payload_to_user(payload, target_id)
        plan = db.session.execute(
            db.select(TrainingPlan).where(TrainingPlan.user_id == target_id)
        ).scalar_one()
        original_session_count = _domain_counts(target_id)["training_sessions"]

    login(client, "new-session-target", "test-password")
    plan_response = client.get(f"/training-plans/{plan.id}")
    assert plan_response.status_code == 200
    assert b"Plan roundtrip completo" in plan_response.data

    select_response = client.get(f"/training-sessions/new?plan_id={plan.id}")
    assert select_response.status_code == 200
    match = re.search(rb'<option value="([^"]+)"', select_response.data)
    assert match is not None
    planned_day = unescape(match.group(1).decode("utf-8"))

    prefill_response = client.get(
        f"/training-sessions/new?plan_id={plan.id}&planned_day={planned_day}"
    )
    assert prefill_response.status_code == 200
    assert b"Sentadilla ficticia" in prefill_response.data

    post_response = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day,
            "performed_at": "2026-07-12T08:00",
            "duration_minutes": "46",
            "average_heart_rate_bpm": "124",
            "calories_burned": "345",
            "notes": "Sesion nueva ficticia desde restore",
            "exercise_0_set_0_completed": "1",
            "exercise_0_set_0_weight_kg": "105",
            "exercise_0_set_0_reps": "5",
            "exercise_0_set_0_rir": "2",
            "exercise_0_set_0_rpe": "8",
            "exercise_0_set_0_rest_seconds": "120",
            "exercise_0_set_1_completed": "1",
            "exercise_0_set_1_weight_kg": "106",
            "exercise_0_set_1_reps": "5",
            "exercise_0_set_1_rir": "1",
            "exercise_0_set_1_rpe": "8.5",
            "exercise_0_set_1_rest_seconds": "135",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 302

    with app.app_context():
        assert _domain_counts(target_id)["training_sessions"] == original_session_count + 1
        new_session = db.session.execute(
            db.select(TrainingSession)
            .where(TrainingSession.user_id == target_id)
            .order_by(TrainingSession.performed_at.desc(), TrainingSession.id.desc())
        ).scalars().first()
        assert new_session.duration_seconds == 46 * 60
        assert new_session.average_heart_rate_bpm == 124
        assert str(new_session.calories_burned) == "345.00"
        assert len(new_session.exercises[0].sets) == 2
        new_session_id = new_session.id
        exercise_id = new_session.exercises[0].id

    history_response = client.get("/training-sessions")
    progress_response = client.get(f"/progress/sessions/{new_session_id}")
    exercise_progress_response = client.get(f"/progress/exercises/{exercise_id}")
    assert history_response.status_code == 200
    assert progress_response.status_code == 200
    assert exercise_progress_response.status_code == 200
    assert b"Sentadilla ficticia" in exercise_progress_response.data


def test_restore_persists_in_new_app_context(app, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("persist-target", "persist@example.test")
        target_id = target.id
        db.session.commit()
        _restore_payload_to_user(payload, target_id)
        db.session.remove()

    with app.app_context():
        assert _domain_counts(target_id)["training_sessions"] == 2
        assert _domain_counts(target_id)["recipes"] == 2
        assert db.session.execute(
            db.select(TrainingPlan).where(TrainingPlan.user_id == target_id)
        ).scalar_one().active_version_number == 2


def test_cross_user_restore_data_is_isolated(app, client, user):
    with app.app_context():
        payload = _complete_roundtrip_payload(user)
        target = _make_user("isolated-target", "isolated-target@example.test")
        target_id = target.id
        third = _make_user("isolated-third", "isolated-third@example.test")
        third_id = third.id
        db.session.commit()

        result = _restore_payload_to_user(payload, target_id)
        plan_id = db.session.execute(
            db.select(TrainingPlan.id).where(TrainingPlan.user_id == target_id)
        ).scalar_one()
        session_id = db.session.execute(
            db.select(TrainingSession.id).where(TrainingSession.user_id == target_id)
        ).scalars().first()
        run_id = result["audit_run_id"]
        assert _domain_counts(third_id)["training_sessions"] == 0

    login(client, "isolated-third", "test-password")
    assert client.get(f"/training-plans/{plan_id}").status_code == 404
    assert client.get(f"/training-sessions/{session_id}").status_code == 404
    assert client.get(f"/imports/history/{run_id}").status_code == 404
    with app.app_context():
        assert _domain_counts(third_id)["training_plans"] == 0
        assert _domain_counts(third_id)["recipes"] == 0


def test_upload_without_binary_is_unsupported(app, client, user):
    with app.app_context():
        target = _make_user("upload-metadata-target", "upload-metadata@example.test")
        target_id = target.id
        payload = {
            "schema_version": "1.0",
            "type": "user_data_export",
            "exported_at": "2026-07-10T00:00:00+00:00",
            "user": {"id": user, "email": "source@example.test", "role": "user"},
            "data": {
                "uploads": [
                    {
                        "id": 99,
                        "original_filename": "archivo-ficticio.json",
                        "detected_type": "weigh_in",
                        "import_status": "imported",
                        "sha256": "a" * 64,
                    }
                ],
                "daily_balances": [],
            },
        }
        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        result = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

        assert preview["plan"]["unsupported"] == 1
        assert result["committed"] is False
        assert result["unsupported"] == 1
        assert db.session.get(ImportRun, result["audit_run_id"]).status == "blocked"
        assert _domain_counts(target_id)["uploads"] == 0

    login(client, "upload-metadata-target", "test-password")
    response = client.get("/account/data")
    assert response.status_code == 200
    assert b"user_data_restore" in response.data


def test_second_confirmation_is_rejected(app, client, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("second-confirm-target", "second-confirm@example.test")
        target_id = target.id
        db.session.commit()

    login(client, "second-confirm-target", "test-password")
    preview = client.post(
        "/account/restore",
        data={"file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "export.json")},
        content_type="multipart/form-data",
    )
    token = _hidden(preview, "confirmation_token")
    first = client.post(
        "/account/restore/confirm",
        data={
            "file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "export.json"),
            "confirmation_token": token,
        },
        content_type="multipart/form-data",
    )
    second = client.post(
        "/account/restore/confirm",
        data={
            "file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "export.json"),
            "confirmation_token": token,
        },
        content_type="multipart/form-data",
    )

    assert first.status_code == 200
    assert b"Resultado final" in first.data
    assert second.status_code == 200
    assert b"ya fue usado" in second.data
    with app.app_context():
        assert _domain_counts(target_id)["training_sessions"] == 1


def test_payload_change_after_preview_is_rejected(app, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("payload-change-target", "payload-change@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        changed = json.loads(json.dumps(payload))
        changed["data"]["daily_energy"][0]["data"]["steps"] = 9999

        try:
            service.commit(
                changed,
                user_id=target_id,
                confirmation_token=preview["confirmation_token"],
            )
        except AccountRestoreError as error:
            assert "preview changed" in str(error)
        else:
            raise AssertionError("changed payload must reject the old token")
        assert _domain_counts(target_id)["daily_energy"] == 0


def test_plan_change_after_preview_is_rejected(app, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("plan-change-target", "plan-change@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        stale_preview = service.preview(payload, user_id=target_id)
        _restore_payload_to_user(payload, target_id)

        try:
            service.commit(
                payload,
                user_id=target_id,
                confirmation_token=stale_preview["confirmation_token"],
            )
        except AccountRestoreError as error:
            assert "preview changed" in str(error)
        else:
            raise AssertionError("changed plan must reject the old token")
        assert _domain_counts(target_id)["training_sessions"] == 1


def test_account_restore_complete_semantic_roundtrip_and_repeated_skip(app, user):
    with app.app_context():
        source = db.session.get(User, user)
        source.email = "complete-source@example.test"
        payload = _complete_account_payload(user)
        source_session_count = db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(
                TrainingSession.user_id == user
            )
        ).scalar_one()
        target = _make_user("complete-target", "complete-target@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        result = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )
        restored_export = build_user_data_document(db.session.get(User, target_id), target_id)

        assert result["committed"] is True
        assert _semantic_export(restored_export) == _semantic_export(payload)
        restored_plan = db.session.execute(
            db.select(TrainingPlan).where(TrainingPlan.user_id == target_id)
        ).scalar_one()
        assert restored_plan.active_version_number == 2
        restored_sessions = db.session.execute(
            db.select(TrainingSession).where(TrainingSession.user_id == target_id)
        ).scalars().all()
        assert len(restored_sessions) == 2
        assert {session.training_plan.user_id for session in restored_sessions} == {target_id}
        assert {session.training_plan_version.user_id for session in restored_sessions} == {target_id}
        assert db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(
                TrainingSession.user_id == user
            )
        ).scalar_one() == source_session_count

        repeat_preview = service.preview(payload, user_id=target_id)
        repeat = service.commit(
            payload,
            user_id=target_id,
            confirmation_token=repeat_preview["confirmation_token"],
        )

        assert repeat["committed"] is True
        assert repeat["inserts"] == 0
        assert repeat["skips"] >= 15
        assert db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(
                TrainingSession.user_id == target_id
            )
        ).scalar_one() == 2


def test_restored_training_data_is_visible_in_web_flows(app, client, user):
    with app.app_context():
        payload = _complete_account_payload(user)
        target = _make_user("roundtrip-web-user", "roundtrip-web@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )
        plan_id = db.session.execute(
            db.select(TrainingPlan.id).where(TrainingPlan.user_id == target_id)
        ).scalar_one()
        session_id = db.session.execute(
            db.select(TrainingSession.id).where(TrainingSession.user_id == target_id)
        ).scalars().first()
        exercise_id = db.session.execute(
            db.select(TrainingSessionExercise.id).where(
                TrainingSessionExercise.user_id == target_id
            )
        ).scalars().first()

    login(client, "roundtrip-web-user", "test-password")
    responses = [
        client.get("/training-plans"),
        client.get(f"/training-plans/{plan_id}"),
        client.get("/training-sessions"),
        client.get(f"/training-sessions/{session_id}"),
        client.get("/progress"),
        client.get(f"/progress/exercises/{exercise_id}"),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert "Plan roundtrip completo".encode() in responses[0].data
    assert "Sentadilla ficticia".encode() in responses[-1].data


def test_account_restore_blocks_recipe_with_missing_product_and_rolls_back(app, user):
    with app.app_context():
        payload = _full_account_payload(user)
        payload["data"]["food_products"] = []
        payload["data"]["recipes"][0]["ingredients"][0]["food_product_name"] = (
            "Producto inexistente ficticio"
        )
        target = _make_user("recipe-missing-product", "missing-product@example.test")
        target_id = target.id
        db.session.commit()

        preview = AccountRestoreService().preview(payload, user_id=target_id)
        result = AccountRestoreService().commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

        assert preview["valid"] is False
        assert result["committed"] is False
        assert result["rollback"] is False
        assert "Recipe ingredient food product" in json.dumps(result)
        assert db.session.execute(
            db.select(db.func.count(FoodProduct.id)).where(FoodProduct.user_id == target_id)
        ).scalar_one() == 0
        run = db.session.execute(
            db.select(ImportRun).where(ImportRun.user_id == target_id)
        ).scalar_one()
        assert run.status == "blocked"


def test_account_restore_rejects_json_limits_and_future_schema(app, user):
    with app.app_context():
        payload = _full_account_payload(user)
        payload["schema_version"] = "999.0"
        try:
            AccountRestoreService().preview(payload, user_id=user)
        except AccountRestoreError as error:
            assert "schema version" in str(error)
        else:
            raise AssertionError("future schema version should fail")

        deep = {
            "schema_version": "1.0",
            "type": "user_data_export",
            "exported_at": "2026-07-10T00:00:00+00:00",
            "user": {"id": 1, "email": None, "role": "user"},
            "data": {"weigh_ins": []},
        }
        cursor = deep["data"]
        for index in range(30):
            cursor["nested"] = {"i": index}
            cursor = cursor["nested"]
        try:
            AccountRestoreService().preview(deep, user_id=user)
        except AccountRestoreError as error:
            assert "deeply nested" in str(error)
        else:
            raise AssertionError("deep JSON should fail")


def test_account_restore_web_requires_login_previews_and_confirms(app, client, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("web-restore", "web-restore@example.test")
        target_id = target.id
        db.session.commit()

    assert client.get("/account/restore").status_code == 302
    login(client, "web-restore", "test-password")
    preview = client.post(
        "/account/restore",
        data={
            "file": (
                io.BytesIO(json.dumps(payload).encode("utf-8")),
                "export.json",
            )
        },
        content_type="multipart/form-data",
    )

    assert preview.status_code == 200
    assert b"Plan de restore" in preview.data
    assert b'name="payload_json"' not in preview.data
    with app.app_context():
        assert db.session.execute(
            db.select(TrainingSession).where(TrainingSession.user_id == target_id)
        ).scalar_one_or_none() is None

    payload_bytes = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/account/restore/confirm",
        data={
            "file": (io.BytesIO(payload_bytes), "export.json"),
            "confirmation_token": _hidden(preview, "confirmation_token"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"Resultado final" in response.data
    with app.app_context():
        assert db.session.execute(
            db.select(TrainingSession).where(TrainingSession.user_id == target_id)
        ).scalar_one()


def test_account_restore_web_rejects_tampered_confirmation(app, client, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("web-restore-tamper", "web-restore-tamper@example.test")
        target_id = target.id
        db.session.commit()

    login(client, "web-restore-tamper", "test-password")
    preview = client.post(
        "/account/restore",
        data={
            "file": (
                io.BytesIO(json.dumps(payload).encode("utf-8")),
                "export.json",
            )
        },
        content_type="multipart/form-data",
    )
    assert b'name="payload_json"' not in preview.data
    tampered = json.loads(json.dumps(payload))
    tampered["data"]["daily_energy"][0]["data"]["date"] = "2026-07-11"

    response = client.post(
        "/account/restore/confirm",
        data={
            "file": (io.BytesIO(json.dumps(tampered).encode("utf-8")), "export.json"),
            "confirmation_token": _hidden(preview, "confirmation_token"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"No fue posible confirmar" in response.data
    with app.app_context():
        assert db.session.execute(
            db.select(TrainingSession).where(TrainingSession.user_id == target_id)
        ).scalar_one_or_none() is None


def test_account_restore_web_rejects_reused_confirmation_token(app, client, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("web-restore-reuse", "web-restore-reuse@example.test")
        target_id = target.id
        db.session.commit()

    login(client, "web-restore-reuse", "test-password")
    preview = client.post(
        "/account/restore",
        data={
            "file": (
                io.BytesIO(json.dumps(payload).encode("utf-8")),
                "export.json",
            )
        },
        content_type="multipart/form-data",
    )
    token = _hidden(preview, "confirmation_token")
    payload_bytes = json.dumps(payload).encode("utf-8")

    first = client.post(
        "/account/restore/confirm",
        data={
            "file": (io.BytesIO(payload_bytes), "export.json"),
            "confirmation_token": token,
        },
        content_type="multipart/form-data",
    )
    second = client.post(
        "/account/restore/confirm",
        data={
            "file": (io.BytesIO(payload_bytes), "export.json"),
            "confirmation_token": token,
        },
        content_type="multipart/form-data",
    )

    assert first.status_code == 200
    assert b"Resultado final" in first.data
    assert second.status_code == 200
    assert b"ya fue usado" in second.data
    with app.app_context():
        assert db.session.execute(
            db.select(db.func.count(TrainingSession.id)).where(
                TrainingSession.user_id == target_id
            )
        ).scalar_one() == 1


def test_account_data_center_shows_restore_and_latest_audit_run(app, client, user):
    with app.app_context():
        payload = _full_account_payload(user)
        target = _make_user("data-center-user", "data-center@example.test")
        target_id = target.id
        db.session.commit()

        service = AccountRestoreService()
        preview = service.preview(payload, user_id=target_id)
        service.commit(
            payload,
            user_id=target_id,
            confirmation_token=preview["confirmation_token"],
        )

    login(client, "data-center-user", "test-password")
    response = client.get("/account/data")

    assert response.status_code == 200
    assert b"Centro de datos" in response.data
    assert b"Exportar respaldo" in response.data
    assert b"Restore desde export" in response.data
    assert b"Importar JSON est" in response.data
    assert b"user_data_restore" in response.data
    assert b"No restaura" in response.data
