"""Synthetic fixtures only; never uses the installation's DB, storage or secrets."""
import copy
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import (DailyEnergy, DailyNutrition, EnergyDay, Exercise, FoodProduct,
                        MedicalLabReport, NutritionItem, NutritionMeal, Recipe,
                        TrainingPlan, TrainingPlanVersion, TrainingSession, TrainingSet, User, WeighIn)
from app.models.nutrition_intelligence import MealLog
from app.services import demo_seed, food_catalog, gym_sessions
from app.services.demo_fixtures import DEMO_EMAIL, DEMO_NAME, DEMO_PUBLIC_ID, DEMO_SOURCE, identity
from app.services.daily_balance import daily_balance
from app.services.dashboard import DashboardDateRange, DashboardRangeError, DashboardSummaryService
from app.services.energy_balance import EnergyBalanceService
from app.services.energy_days import views
from app.services.exporters.training_session import build_completed_workout_document
from app.services.validation import validate_json_document
from tests.conftest import DEMO_TEST_PASSWORD, login

AS_OF = date(2026, 11, 18)


def seed(app, day=AS_OF, confirmed=True):
    args = ["seed", "demo", "--as-of", day.isoformat()]
    if confirmed:
        args.append("--confirm-local")
    return app.test_cli_runner().invoke(args=args)


def count(model):
    return db.session.scalar(db.select(db.func.count()).select_from(model))


def owner():
    return db.session.scalar(db.select(User).where(User.public_id == DEMO_PUBLIC_ID))


def period(start, end, compare=None):
    return DashboardDateRange.from_query({"from": start, "to": end, "compare": compare}, "UTC")


def test_creation_login_hash_scope_and_no_future(demo_enabled, client):
    result = seed(demo_enabled)
    assert result.exit_code == 0, result.output
    assert DEMO_EMAIL in result.output and DEMO_TEST_PASSWORD not in result.output
    assert "training_sessions=21" in result.output and "training_sets=378" in result.output
    with demo_enabled.app_context():
        user = owner()
        assert (user.username, user.email, user.display_name, user.role, user.is_active) == (DEMO_EMAIL, DEMO_EMAIL, DEMO_NAME, "user", True)
        assert user.check_password(DEMO_TEST_PASSWORD)
        assert user.password_hash != DEMO_TEST_PASSWORD
        assert not user.check_password("incorrect-fictional-password")
        assert count(DailyEnergy) == count(DailyNutrition) == count(EnergyDay) == 49
        assert count(TrainingSession) == 21 and count(TrainingSet) == 378
        assert count(TrainingPlan) == count(TrainingPlanVersion) == 1
        assert count(Recipe) == 12 and count(Exercise) == 8
        assert count(WeighIn) == 49 and count(MedicalLabReport) == 0
        for model in (DailyNutrition, DailyEnergy):
            days = db.session.scalars(db.select(model).order_by(model.date)).all()
            assert days[0].date == date(2026, 10, 1) and days[-1].date == AS_OF
            assert all(row.user_id == user.id and row.source == DEMO_SOURCE for row in days)
        sessions = db.session.scalars(db.select(TrainingSession).order_by(TrainingSession.performed_at)).all()
        assert all(s.performed_at.date() <= AS_OF and s.completed_at.date() <= AS_OF for s in sessions)
        assert all(s.status == "completed" and s.training_plan_version.user_id == user.id for s in sessions)
        assert all((b.performed_at - a.performed_at).days >= 2 for a, b in zip(sessions, sessions[1:]))
        assert all(s.duration_seconds == int((s.completed_at - s.started_at).total_seconds()) for s in sessions)
    assert login(client, DEMO_EMAIL, "incorrect-fictional-password").status_code == 200
    assert login(client, DEMO_EMAIL, DEMO_TEST_PASSWORD).status_code == 302
    assert client.get("/admin/users").status_code == 403


def test_macros_daily_energy_and_real_sets(demo_enabled, demo_account):
    with demo_enabled.app_context():
        user = owner()
        balances, active, resting = [], [], []
        days = db.session.scalars(db.select(DailyNutrition).order_by(DailyNutrition.date)).all()
        for day in days:
            items = [item for meal in day.meals for item in meal.items]
            assert 3 <= len(day.meals) <= 5
            assert 1950 <= day.calories <= 2650
            assert 120 <= day.protein_g <= 180 and 55 <= day.fat_g <= 95
            assert 20 <= day.fiber_g <= 36
            for field in ("calories", "protein_g", "fat_g", "total_carbs_g", "net_carbs_g", "fiber_g"):
                assert getattr(day, field) == sum(getattr(item, field) for item in items)
            assert abs(day.calories - (4 * (day.protein_g + day.total_carbs_g) + 9 * day.fat_g)) < Decimal(".02")
            assert abs(day.total_carbs_g - day.net_carbs_g - day.fiber_g) < Decimal(".01")
            assert day.sodium_mg is None
            result = daily_balance(user.id, day.date)
            energy = result["energy"]
            assert result["complete"] and result["calories_consumed"] == day.calories
            assert 2250 <= energy.total_calories <= 3000
            assert energy.total_calories == energy.active_calories + energy.resting_calories
            assert result["balance"] == day.calories - energy.total_calories
            assert len(energy.evidence) == 1
            balances.append(result["balance"])
            (active if day.date.weekday() in {0, 2, 4} else resting).append(energy.active_calories)
        assert min(balances) < -100 and max(balances) > 50 and any(abs(b) <= 35 for b in balances)
        assert -15000 < sum(balances) < -1000
        assert sum(active) / len(active) > sum(resting) / len(resting)
        logs = db.session.scalars(db.select(MealLog)).all()
        assert len(logs) == 196
        assert all(e["food"]["scope"] == "user" for log in logs for e in log.snapshot_json["ingredients"])
        assert all("iron" not in log.snapshot_json["ingredients"][0]["food"]["nutrients"] for log in logs)
        sessions = db.session.scalars(db.select(TrainingSession).order_by(TrainingSession.performed_at)).all()
        weights, repetitions = {}, {}
        for session in sessions:
            document = build_completed_workout_document(session, user.id)
            validate_json_document(document, "completed_workout")
            assert len(session.exercises) == 6
            for exercise in session.exercises:
                assert len(exercise.sets) == 3
                weights.setdefault(exercise.name, []).append(exercise.sets[0].weight_kg)
                repetitions.setdefault(exercise.name, []).append(sum(s.reps for s in exercise.sets))
                for s in exercise.sets:
                    assert s.user_id == user.id and s.weight_kg > 0 and 6 <= s.reps <= 13
                    assert s.planned_set_number == s.set_number and s.rest_seconds in {90, 120}
                    assert 1 <= s.rir <= 3 and s.rpe == 10 - s.rir
        assert all(values[-1] > values[0] for values in weights.values())
        assert any(any(b < a for a, b in zip(values, values[1:])) for values in repetitions.values())


def test_replay_and_extension_leave_history_byte_for_byte(demo_enabled, demo_account):
    with demo_enabled.app_context():
        user = owner()
        original = [(row.id, row.date, row.raw_payload_json, row.updated_at) for row in db.session.scalars(db.select(DailyEnergy)).all()]
        logs = copy.deepcopy([log.snapshot_json for log in db.session.scalars(db.select(MealLog)).all()])
        password_hash = user.password_hash
        before = {model: count(model) for model in (User, Recipe, FoodProduct, NutritionItem, TrainingSession, TrainingSet)}
    replay = seed(demo_enabled)
    assert replay.exit_code == 0, replay.output
    assert "Registros creados en esta ejecución: 0" in replay.output
    with demo_enabled.app_context():
        assert before == {model: count(model) for model in before}
        assert owner().password_hash == password_hash
    # Historical deterministic update independent of today's date, within November.
    with demo_enabled.app_context():
        from unittest.mock import patch
        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 12, 2, 20, tzinfo=tz)
        with patch.object(demo_seed, "datetime", Later):
            _, created = demo_seed.seed_demo_data(as_of=date(2026, 12, 2), confirmed=True)
        assert created["nutrition_days"] == created["energy_days"] == 14
        assert original == [(row.id, row.date, row.raw_payload_json, row.updated_at) for row in db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.date <= AS_OF)).all()]
        assert logs == [log.snapshot_json for log in db.session.scalars(db.select(MealLog).where(MealLog.local_date <= AS_OF)).all()]


def test_reproducible_across_fresh_accounts_and_as_of(demo_enabled):
    with demo_enabled.app_context():
        user, _ = demo_seed.seed_demo_data(as_of=date(2026, 10, 18), confirmed=True)
        original = [(d.date, d.calories, d.protein_g, d.fat_g) for d in db.session.scalars(db.select(DailyNutrition).order_by(DailyNutrition.date))]
        energy = [(d.date, d.total_calories, d.steps) for d in views(user.id)]
        # Rollback behaviour is tested separately; rebuilding only this ephemeral DB.
        db.session.remove()
        db.drop_all()
        db.create_all()
        user, _ = demo_seed.seed_demo_data(as_of=date(2026, 10, 18), confirmed=True)
        assert original == [(d.date, d.calories, d.protein_g, d.fat_g) for d in db.session.scalars(db.select(DailyNutrition).order_by(DailyNutrition.date))]
        assert energy == [(d.date, d.total_calories, d.steps) for d in views(user.id)]


@pytest.mark.parametrize("config,confirmed", [
    ({"DEMO_SEED_ENABLED": False}, True), ({}, False),
    ({"DEMO_SEED_ENVIRONMENT": "production"}, True),
    ({"APP_ENV": "production"}, True), ({"ENV": "production"}, True),
    ({"DEMO_SEED_ENVIRONMENT": "test", "TESTING": False}, True),
    ({"NUTRITION_INTELLIGENCE_ENABLED": False}, True),
])
def test_unauthorized_environment_has_no_writes(demo_enabled, config, confirmed):
    demo_enabled.config.update(config)
    result = seed(demo_enabled, confirmed=confirmed)
    assert result.exit_code != 0
    with demo_enabled.app_context():
        assert count(User) == count(DailyNutrition) == count(TrainingPlan) == 0


@pytest.mark.parametrize("password", [None, "short"])
def test_missing_password_rejected(demo_enabled, monkeypatch, password):
    if password is None:
        monkeypatch.delenv("DEMO_USER_PASSWORD")
    else:
        monkeypatch.setenv("DEMO_USER_PASSWORD", password)
    assert seed(demo_enabled).exit_code != 0
    with demo_enabled.app_context():
        assert count(User) == 0


def test_future_rejected_before_user_created(demo_enabled):
    assert seed(demo_enabled, datetime.now().date() + timedelta(days=10)).exit_code != 0
    with demo_enabled.app_context():
        assert count(User) == 0


def test_production_requires_explicit_matching_confirmation(demo_enabled):
    demo_enabled.config.update(DEMO_SEED_ENVIRONMENT="production", APP_ENV="production")
    assert seed(demo_enabled).exit_code != 0
    result = demo_enabled.test_cli_runner().invoke(args=["seed", "demo", "--as-of", AS_OF.isoformat(), "--confirm-production"])
    assert result.exit_code == 0, result.output
    assert "training_sets=378" in result.output
    assert demo_enabled.test_cli_runner().invoke(args=["seed", "demo", "--confirm-production", "--confirm-local"]).exit_code != 0


def test_production_confirmation_rejected_for_local_environment(demo_enabled):
    result = demo_enabled.test_cli_runner().invoke(args=["seed", "demo", "--confirm-production"])
    assert result.exit_code != 0
    with demo_enabled.app_context():
        assert count(User) == 0


def test_email_collision_never_adopts_or_changes_account(demo_enabled):
    with demo_enabled.app_context():
        user = User(username="existing-qa", email=DEMO_EMAIL, role="admin")
        user.set_password("fictional-existing-password")
        db.session.add(user)
        db.session.commit()
        password_hash = user.password_hash
    result = seed(demo_enabled)
    assert result.exit_code != 0
    with demo_enabled.app_context():
        user = db.session.scalar(db.select(User))
        assert (user.username, user.role, user.password_hash) == ("existing-qa", "admin", password_hash)
        assert count(DailyNutrition) == count(TrainingSession) == 0


def test_entire_seed_rolls_back_on_late_failure(demo_enabled, monkeypatch):
    real = demo_seed._session
    def fail(*args):
        real(*args)
        if args[3] == date(2026, 10, 7):
            raise demo_seed.DemoSeedError("Fallo ficticio de QA")
    monkeypatch.setattr(demo_seed, "_session", fail)
    assert seed(demo_enabled).exit_code != 0
    with demo_enabled.app_context():
        for model in (User, DailyEnergy, EnergyDay, DailyNutrition, NutritionItem, Recipe, FoodProduct, TrainingPlan, TrainingSet):
            assert count(model) == 0


def test_dashboards_months_metrics_and_two_user_isolation(demo_enabled, client, user, demo_account):
    with demo_enabled.app_context():
        before = db.session.get(User, user).password_hash
        demo = owner()
        current = period("2026-11-01", "2026-11-18", "month-to-date")
        result = DashboardSummaryService().build(demo.id, current, "kg")
        assert result["previous_period"]["range"]["from"] == "2026-10-01"
        assert result["previous_period"]["range"]["to"] == "2026-10-18"
        assert result["summary"]["training"]["sessions"] == 8
        energy = EnergyBalanceService().build(demo.id, current, include_daily=True)
        assert energy["coverage"]["both_known_days"] == 18
        assert energy["comparison"]["mode"] == "month-to-date"
        assert Decimal(result["summary"]["energy"]["consumed_total"]) == energy["metrics"]["consumed_kcal"]
        assert Decimal(result["summary"]["energy"]["balance_total"]) == energy["metrics"]["balance_kcal"]
        october = EnergyBalanceService().build(demo.id, period("2026-10-01", "2026-10-31"))
        assert october["coverage"]["both_known_days"] == 31
        assert db.session.get(User, user).password_hash == before
        assert not views(user)
        assert not db.session.scalars(db.select(DailyNutrition).where(DailyNutrition.user_id == user)).all()
        session = db.session.scalar(db.select(TrainingSession).where(TrainingSession.user_id == demo.id))
        session_id, public_id = session.id, session.public_id
    login(client, DEMO_EMAIL, DEMO_TEST_PASSWORD)
    for path in ("/dashboard?from=2026-11-01&to=2026-11-18&compare=month-to-date", "/dashboard?preset=previous-month&as_of=2026-11-18", "/energy?date=2026-11-18", "/nutrition/?date=2026-11-18", "/gym", "/training-sessions", "/progress"):
        assert client.get(path, follow_redirects=True).status_code == 200, path
    client.post("/logout")
    login(client)
    assert client.get(f"/training-sessions/{session_id}").status_code == 404
    with demo_enabled.app_context():
        with pytest.raises(gym_sessions.GymError):
            gym_sessions.owned_session(user, public_id)


def test_month_to_date_leap_year_and_invalid_ranges():
    march = period("2024-03-01", "2024-03-31", "month-to-date")
    assert march.previous_start == date(2024, 2, 1) and march.previous_end == date(2024, 2, 29)
    with pytest.raises(DashboardRangeError):
        period("2026-11-02", "2026-11-18", "month-to-date")


def test_active_catalog_reused_and_snapshot_preserves_micros(demo_enabled):
    from pathlib import Path
    import json
    source = Path(__file__).resolve().parents[2] / "examples/catalog/nutrition-2-1/usda_sr_legacy.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    wanted = {f[0] for f in demo_seed.FOODS.values()}
    document["foods"] = [f for f in document["foods"] if f["source_food_id"] in wanted]
    document["revision"] = "qa-demo-subset"
    with demo_enabled.app_context():
        revision = food_catalog.stage(document)
        food_catalog.activate(document["source"], revision.revision, 1)
        db.session.commit()
    result = seed(demo_enabled)
    assert result.exit_code == 0, result.output
    with demo_enabled.app_context():
        assert count(FoodProduct) == 0
        logs = db.session.scalars(db.select(MealLog)).all()
        ingredients = [e for log in logs for e in log.snapshot_json["ingredients"]]
        assert all(e["food"]["scope"] == "catalog" for e in ingredients)
        assert any(e["food"]["nutrients"].get("iron", {}).get("state") == "known" for e in ingredients)
        for day in db.session.scalars(db.select(DailyNutrition)):
            assert 1850 <= day.calories <= 2700 and 110 <= day.protein_g <= 190


def test_real_exercise_catalog_reference_is_reused(demo_enabled):
    from app.models import ExerciseCatalogSource, ExternalExercise
    from app.services.exercise_identity import normalize_exercise_name
    with demo_enabled.app_context():
        db.session.add(ExerciseCatalogSource(source_id="free-exercise-db", active_snapshot="qa-demo-v1", manifest={}))
        db.session.flush()
        reference = ExternalExercise(source="free-exercise-db", external_id="Machine_Bench_Press",
            name="Machine Bench Press", normalized_name=normalize_exercise_name("Machine Bench Press"), details={}, media=[])
        db.session.add(reference)
        db.session.commit()
        reference_id = reference.id
    result = seed(demo_enabled)
    assert result.exit_code == 0, result.output
    with demo_enabled.app_context():
        mapped = db.session.scalar(db.select(Exercise).where(Exercise.external_catalog_id == reference_id))
        assert mapped.canonical_name == "Machine Bench Press"
        assert count(ExternalExercise) == 1 and count(Exercise) == 8
