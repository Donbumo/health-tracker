from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    FoodProduct,
    MedicalLabReport,
    Recipe,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    User,
    WeighIn,
)
from app.services.importers.standard_import_executor import (
    StandardImportError,
    StandardImportExecutor,
)


def _energy_document(user_id: int, date_value: str = "2026-07-20", calories: int = 2400):
    return {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "date": date_value,
            "source": "qa",
            "total_expenditure_kcal": calories,
            "active_expenditure_kcal": 700,
        },
    }


def _weigh_in_document(user_id: int, recorded_at: str = "2026-07-20T08:00:00+00:00") -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "weigh_in",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "recorded_at": recorded_at,
            "weight_kg": 82.5,
            "body_fat_percent": 22.0,
            "source": "qa",
        },
    }


def _nutrition_document(user_id: int, date_value: str = "2026-07-20") -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "daily_nutrition",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "date": date_value,
            "source": "qa",
            "notes": "nota nutrición QA",
            "meals": [
                {
                    "meal_type": "breakfast",
                    "name": "Desayuno QA",
                    "items": [
                        {
                            "name": "Item QA",
                            "quantity": 100,
                            "unit": "g",
                            "calories_kcal": 250,
                            "protein_g": 20,
                        }
                    ],
                }
            ],
        },
    }


def _food_document(user_id: int, name: str = "Producto demo QA"):
    return {
        "schema_version": "1.0",
        "type": "food_product",
        "user_id": user_id,
        "source_type": "uploaded",
        "name": name,
        "brand": "Marca demo",
        "calories_per_100g": 100,
        "protein_g_per_100g": 20,
    }


def _medical_lab_document(user_id: int, date_value: str = "2026-07-20") -> dict:
    return {
        "schema_version": "1.0",
        "type": "medical_lab",
        "user_id": user_id,
        "source_type": "uploaded",
        "date": date_value,
        "laboratory_name": "Laboratorio QA",
        "notes": "nota médica QA",
        "markers": [
            {
                "name": "Glucosa QA",
                "value": 90,
                "unit": "mg/dL",
                "status": "normal",
            }
        ],
    }


def _training_plan_document(
    user_id: int,
    *,
    name: str = "Rutina estándar QA",
    description: str | None = "descripción inicial",
    reps: int = 8,
) -> dict:
    data = {
        "name": name,
        "weeks": [
            {
                "week_number": 1,
                "days": [
                    {
                        "day_number": 1,
                        "name": "Día QA",
                        "exercises": [
                            {
                                "exercise_order": 1,
                                "name": "Press QA",
                                "sets": [
                                    {
                                        "set_number": 1,
                                        "reps": reps,
                                    }
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


def _completed_workout_document(
    user_id: int,
    *,
    plan_id: int,
    version_id: int,
    performed_at: str = "2026-07-20T10:00:00+00:00",
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
            "exercises": [
                {
                    "exercise_order": 1,
                    "planned_exercise_order": 1,
                    "name": "Press QA",
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


def _recipe_document(
    user_id: int,
    *,
    name: str = "Receta demo QA",
) -> dict:
    return {
        "schema_version": "1.0",
        "type": "recipe",
        "user_id": user_id,
        "source_type": "uploaded",
        "name": name,
        "servings": 2,
        "ingredients": [
            {
                "food_product_name": "Producto receta QA",
                "quantity_g": 50,
            }
        ],
    }


def _seed_recipe_product(user_id: int) -> None:
    db.session.add(
        FoodProduct(
            user_id=user_id,
            name="Producto receta QA",
            brand=None,
            source="qa",
            calories_per_100g=100,
            protein_g_per_100g=10,
            is_active=True,
        )
    )
    db.session.commit()


def _recipe_bundle_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "type": "recipe_bundle",
        "user_id": user_id,
        "source_type": "uploaded",
        "name": "Bundle demo QA",
        "recipes": [
            _recipe_document(user_id, name="Receta bundle uno"),
            _recipe_document(user_id, name="Receta bundle dos"),
        ],
    }


def test_confirmed_import_requires_confirmation(app, user):
    document = _energy_document(user)

    with app.app_context():
        executor = StandardImportExecutor()
        try:
            executor.commit_documents(
                [document],
                user_id=user,
                target_type="daily_energy",
                confirmed=False,
            )
        except StandardImportError as error:
            assert "confirmation" in str(error)
        else:
            raise AssertionError("commit without confirmation should fail")

        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_confirmed_import_inserts_and_repeated_import_skips(app, user):
    document = _energy_document(user)

    with app.app_context():
        executor = StandardImportExecutor()
        first = executor.commit_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        second = executor.commit_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        assert first["inserts"] == 1
        assert first["committed"] is True
        assert second["skips"] == 1
        assert db.session.execute(db.select(DailyEnergy)).scalars().all()[0].user_id == user


def test_confirmed_import_updates_same_user_natural_key(app, user):
    document = _energy_document(user, calories=2400)
    updated = _energy_document(user, calories=2500)

    with app.app_context():
        executor = StandardImportExecutor()
        executor.commit_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        result = executor.commit_documents(
            [updated],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert result["updates"] == 1
        assert int(record.total_calories) == 2500


def test_confirmed_import_partial_daily_energy_update_preserves_absent_fields(app, user):
    original = _energy_document(user, calories=2400)
    original["data"]["notes"] = "nota inicial"
    partial = _energy_document(user, calories=2500)
    partial["data"].pop("active_expenditure_kcal")
    partial["data"].pop("source")

    with app.app_context():
        executor = StandardImportExecutor()
        executor.commit_documents(
            [original],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        result = executor.commit_documents(
            [partial],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert result["updates"] == 1
        assert int(record.total_calories) == 2500
        assert int(record.active_calories) == 700
        assert record.source == "qa"
        assert record.notes == "nota inicial"


def test_confirmed_import_rejects_other_user_id(app, user):
    document = _energy_document(user_id=user + 100)

    with app.app_context():
        result = StandardImportExecutor().commit_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        assert result["committed"] is False
        assert result["invalid"] == 1
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_confirmed_import_supports_weigh_in_insert_skip_and_partial_update(app, user):
    original = _weigh_in_document(user)
    partial = _weigh_in_document(user)
    partial["data"]["weight_kg"] = 83.0
    partial["data"].pop("body_fat_percent")

    with app.app_context():
        executor = StandardImportExecutor()
        first = executor.commit_documents(
            [original],
            user_id=user,
            target_type="weigh_in",
            confirmed=True,
        )
        second = executor.commit_documents(
            [original],
            user_id=user,
            target_type="weigh_in",
            confirmed=True,
        )
        updated = executor.commit_documents(
            [partial],
            user_id=user,
            target_type="weigh_in",
            confirmed=True,
        )

        record = db.session.execute(db.select(WeighIn)).scalar_one()
        assert first["inserts"] == 1
        assert second["skips"] == 1
        assert updated["updates"] == 1
        assert float(record.weight_kg) == 83.0
        assert float(record.body_fat_percentage) == 22.0


def test_confirmed_import_supports_daily_nutrition_insert_skip_and_partial_update(app, user):
    original = _nutrition_document(user)
    partial = _nutrition_document(user)
    partial["data"].pop("notes")
    partial["data"].pop("meals")
    partial["data"]["calories_kcal"] = 300

    with app.app_context():
        executor = StandardImportExecutor()
        first = executor.commit_documents(
            [original],
            user_id=user,
            target_type="daily_nutrition",
            confirmed=True,
        )
        second = executor.commit_documents(
            [original],
            user_id=user,
            target_type="daily_nutrition",
            confirmed=True,
        )
        updated = executor.commit_documents(
            [partial],
            user_id=user,
            target_type="daily_nutrition",
            confirmed=True,
        )

        record = db.session.execute(db.select(DailyNutrition)).scalar_one()
        assert first["inserts"] == 1
        assert second["skips"] == 1
        assert updated["updates"] == 1
        assert int(record.calories) == 300
        assert record.notes == "nota nutrición QA"
        assert len(record.meals) == 1


def test_confirmed_import_batch_is_atomic_on_invalid_document(app, user):
    valid = _energy_document(user, date_value="2026-07-20")
    invalid = _energy_document(user, date_value="2026-07-21")
    del invalid["data"]["date"]

    with app.app_context():
        result = StandardImportExecutor().commit_documents(
            [valid, invalid],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

        assert result["committed"] is False
        assert result["invalid"] == 1
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_confirmed_import_isolated_by_user(app, user):
    with app.app_context():
        second = User(username="standard-import-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

        executor = StandardImportExecutor()
        executor.commit_documents(
            [_energy_document(user, date_value="2026-07-20")],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        executor.commit_documents(
            [_energy_document(second_id, date_value="2026-07-20")],
            user_id=second_id,
            target_type="daily_energy",
            confirmed=True,
        )

        records = db.session.execute(
            db.select(DailyEnergy).order_by(DailyEnergy.user_id)
        ).scalars().all()
        assert {record.user_id for record in records} == {user, second_id}


def test_confirmed_import_preview_from_assisted_payload_is_read_only(app, user):
    payload = {
        "energia": [
            {
                "fecha": "2026-07-22",
                "calorias_totales": 2300,
            }
        ]
    }

    with app.app_context():
        result = StandardImportExecutor().preview_payload(
            payload,
            user_id=user,
            requested_type="daily_energy",
        )

        assert result["read_only"] is True
        assert result["plan"]["inserts"] == 1
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_confirmed_import_supports_food_product_insert(app, user):
    with app.app_context():
        result = StandardImportExecutor().commit_documents(
            [_food_document(user)],
            user_id=user,
            target_type="food_products",
            confirmed=True,
        )

        product = db.session.execute(db.select(FoodProduct)).scalar_one()
        assert result["inserts"] == 1
        assert product.user_id == user
        assert product.name == "Producto demo QA"


def test_confirmed_import_supports_food_product_skip_and_partial_update(app, user):
    original = _food_document(user, name="Producto parcial QA")
    original["notes"] = "nota producto"
    partial = _food_document(user, name="Producto parcial QA")
    partial["calories_per_100g"] = 120
    partial.pop("protein_g_per_100g")

    with app.app_context():
        executor = StandardImportExecutor()
        executor.commit_documents(
            [original],
            user_id=user,
            target_type="food_products",
            confirmed=True,
        )
        repeat = executor.commit_documents(
            [original],
            user_id=user,
            target_type="food_products",
            confirmed=True,
        )
        updated = executor.commit_documents(
            [partial],
            user_id=user,
            target_type="food_products",
            confirmed=True,
        )

        product = db.session.execute(
            db.select(FoodProduct).where(FoodProduct.name == "Producto parcial QA")
        ).scalar_one()
        assert repeat["skips"] == 1
        assert updated["updates"] == 1
        assert int(product.calories_per_100g) == 120
        assert int(product.protein_g_per_100g) == 20
        assert product.notes == "nota producto"


def test_confirmed_import_supports_medical_lab_insert_skip_and_partial_update(app, user):
    original = _medical_lab_document(user)
    partial = _medical_lab_document(user)
    partial.pop("notes")
    partial["markers"][0]["value"] = 95

    with app.app_context():
        executor = StandardImportExecutor()
        first = executor.commit_documents(
            [original],
            user_id=user,
            target_type="medical_lab",
            confirmed=True,
        )
        repeat = executor.commit_documents(
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

        report = db.session.execute(db.select(MedicalLabReport)).scalar_one()
        assert first["inserts"] == 1
        assert repeat["skips"] == 1
        assert updated["updates"] == 1
        assert report.notes == "nota médica QA"
        assert float(report.results[0].value) == 95.0


def test_confirmed_import_supports_training_plan_insert_skip_update_and_preserves_description(app, user):
    original = _training_plan_document(user)
    updated_document = _training_plan_document(user, description=None, reps=10)

    with app.app_context():
        executor = StandardImportExecutor()
        first = executor.commit_documents(
            [original],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
        )
        repeat = executor.commit_documents(
            [original],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
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
        assert repeat["skips"] == 1
        assert updated["updates"] == 1
        assert plan.description == "descripción inicial"
        assert plan.active_version_number == 2
        assert [version.version_number for version in versions] == [1, 2]


def test_confirmed_import_supports_completed_workout_insert_and_conflict_on_repeat(app, user):
    with app.app_context():
        executor = StandardImportExecutor()
        executor.commit_documents(
            [_training_plan_document(user)],
            user_id=user,
            target_type="training_plan",
            confirmed=True,
        )
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        version = db.session.execute(db.select(TrainingPlanVersion)).scalar_one()
        document = _completed_workout_document(
            user,
            plan_id=plan.id,
            version_id=version.id,
        )

        first = executor.commit_documents(
            [document],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )
        repeat = executor.commit_documents(
            [document],
            user_id=user,
            target_type="completed_workout",
            confirmed=True,
        )

        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        assert first["inserts"] == 1
        assert session.user_id == user
        assert repeat["committed"] is False
        assert repeat["conflicts"] == 1


def test_confirmed_import_rejects_empty_documents(app, user):
    with app.app_context():
        try:
            StandardImportExecutor().plan_documents(
                [],
                user_id=user,
                target_type="daily_energy",
            )
        except StandardImportError as error:
            assert "No standard documents" in str(error)
        else:
            raise AssertionError("empty document plans should fail")


def test_confirmed_import_rejects_empty_or_unknown_target(app, user):
    with app.app_context():
        for target_type in ("", "unknown_target"):
            try:
                StandardImportExecutor().plan_documents(
                    [_energy_document(user)],
                    user_id=user,
                    target_type=target_type,
                )
            except StandardImportError as error:
                assert "Unsupported" in str(error)
            else:
                raise AssertionError(f"{target_type!r} should fail")


def test_confirmation_token_detects_changed_plan(app, user):
    document = _energy_document(user)

    with app.app_context():
        executor = StandardImportExecutor()
        initial_plan = executor.plan_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
        )
        token = executor.build_confirmation_token(
            user_id=user,
            target_type="daily_energy",
            payload=document,
            plan=initial_plan,
        )
        executor.commit_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )
        changed_plan = executor.plan_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
        )

        try:
            executor.verify_confirmation_token(
                token,
                user_id=user,
                target_type="daily_energy",
                payload=document,
                plan=changed_plan,
            )
        except StandardImportError as error:
            assert "changed" in str(error)
        else:
            raise AssertionError("changed import plans should invalidate the token")


def test_confirmation_token_can_expire(app, user):
    document = _energy_document(user)

    with app.app_context():
        executor = StandardImportExecutor()
        plan = executor.plan_documents(
            [document],
            user_id=user,
            target_type="daily_energy",
        )
        token = executor.build_confirmation_token(
            user_id=user,
            target_type="daily_energy",
            payload=document,
            plan=plan,
        )

        try:
            executor.verify_confirmation_token(
                token,
                user_id=user,
                target_type="daily_energy",
                payload=document,
                plan=plan,
                max_age=-1,
            )
        except StandardImportError as error:
            assert "expired" in str(error)
        else:
            raise AssertionError("expired confirmation tokens should fail")


def test_confirmed_import_rolls_back_batch_when_write_fails(app, user, monkeypatch):
    documents = [
        _energy_document(user, date_value="2026-07-20"),
        _energy_document(user, date_value="2026-07-21"),
    ]

    with app.app_context():
        executor = StandardImportExecutor()
        original_apply = executor._apply_document
        calls = {"count": 0}

        def fail_after_first(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated write failure")
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
        assert result["errors"] == ["simulated write failure"]
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_recipe_bundle_import_inserts_and_repeated_import_skips(app, user):
    with app.app_context():
        _seed_recipe_product(user)
        bundle = _recipe_bundle_document(user)
        executor = StandardImportExecutor()

        first = executor.commit_documents(
            [bundle],
            user_id=user,
            target_type="recipe_bundle",
            confirmed=True,
        )
        second = executor.commit_documents(
            [bundle],
            user_id=user,
            target_type="recipe_bundle",
            confirmed=True,
        )

        assert first["inserts"] == 2
        assert first["committed"] is True
        assert second["skips"] == 2
        assert all(operation["recipe_index"] in {0, 1} for operation in first["operations"])
        recipes = db.session.execute(db.select(Recipe).order_by(Recipe.name)).scalars().all()
        assert [recipe.name for recipe in recipes] == [
            "Receta bundle dos",
            "Receta bundle uno",
        ]


def test_recipe_bundle_empty_is_invalid_and_not_committed(app, user):
    empty_bundle = {
        "schema_version": "1.0",
        "type": "recipe_bundle",
        "user_id": user,
        "source_type": "uploaded",
        "recipes": [],
    }

    with app.app_context():
        result = StandardImportExecutor().commit_documents(
            [empty_bundle],
            user_id=user,
            target_type="recipe_bundle",
            confirmed=True,
        )

        assert result["committed"] is False
        assert result["invalid"] == 1
        assert "contains invalid or conflicting" in result["errors"][0]
        assert db.session.execute(db.select(Recipe)).scalars().all() == []


def test_recipe_bundle_import_updates_one_recipe_and_inserts_another(app, user):
    with app.app_context():
        _seed_recipe_product(user)
        executor = StandardImportExecutor()
        executor.commit_documents(
            [_recipe_document(user, name="Receta bundle uno")],
            user_id=user,
            target_type="recipe",
            confirmed=True,
        )
        bundle = _recipe_bundle_document(user)
        bundle["recipes"][0]["notes"] = "Cambio QA"

        result = executor.commit_documents(
            [bundle],
            user_id=user,
            target_type="recipe_bundle",
            confirmed=True,
        )

        assert result["updates"] == 1
        assert result["inserts"] == 1
        recipe = db.session.execute(
            db.select(Recipe).where(Recipe.name == "Receta bundle uno")
        ).scalar_one()
        assert recipe.notes == "Cambio QA"


def test_confirmed_import_partial_recipe_update_preserves_absent_optional_fields(app, user):
    with app.app_context():
        _seed_recipe_product(user)
        original = _recipe_document(user, name="Receta parcial QA")
        original["description"] = "descripción original"
        original["notes"] = "nota original"
        partial = _recipe_document(user, name="Receta parcial QA")

        executor = StandardImportExecutor()
        executor.commit_documents(
            [original],
            user_id=user,
            target_type="recipe",
            confirmed=True,
        )
        result = executor.commit_documents(
            [partial],
            user_id=user,
            target_type="recipe",
            confirmed=True,
        )

        recipe = db.session.execute(
            db.select(Recipe).where(Recipe.name == "Receta parcial QA")
        ).scalar_one()
        assert result["updates"] == 1
        assert recipe.description == "descripción original"
        assert recipe.notes == "nota original"


def test_recipe_bundle_import_isolated_by_user(app, user):
    with app.app_context():
        second = User(username="recipe-bundle-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id
        _seed_recipe_product(user)
        _seed_recipe_product(second_id)

        executor = StandardImportExecutor()
        first = executor.commit_documents(
            [_recipe_bundle_document(user)],
            user_id=user,
            target_type="recipe_bundle",
            confirmed=True,
        )
        second_result = executor.commit_documents(
            [_recipe_bundle_document(second_id)],
            user_id=second_id,
            target_type="recipe_bundle",
            confirmed=True,
        )

        assert first["inserts"] == 2
        assert second_result["inserts"] == 2
        user_recipes = db.session.execute(
            db.select(Recipe).where(Recipe.user_id == user)
        ).scalars().all()
        second_recipes = db.session.execute(
            db.select(Recipe).where(Recipe.user_id == second_id)
        ).scalars().all()
        counts = {user: len(user_recipes), second_id: len(second_recipes)}
        assert counts == {user: 2, second_id: 2}
