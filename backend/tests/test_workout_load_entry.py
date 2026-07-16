import uuid
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.extensions import db
from app.models import (
    Exercise,
    ExerciseAlias,
    ExerciseLoadProfile,
    TrainingSession,
    TrainingSet,
    User,
)
from app.services.exporters.training_session import build_completed_workout_document
from app.services.exporters.user_data import build_user_data_document
from app.services.account_restore import AccountRestoreService
from app.services.validation import validate_json_document
from app.services.workout_loads import (
    LB_TO_KG,
    WorkoutLoadError,
    calculate_workout_load,
    load_entry_defaults,
    validate_load_details,
    upsert_exercise_load_profile,
)
from app.services.workout_sessions import list_planned_days
from app.services.overload import exercise_metrics
from app.services.workout_drafts import validate_draft_payload
from tests.conftest import login
from tests.test_phase_4 import _import_plan


@pytest.mark.parametrize(
    ("mode", "components", "expected_lb"),
    [
        ("machine_external_per_side_initial_total", {"external_per_side": "115", "initial_total": "167"}, Decimal("397")),
        ("machine_initial_per_side", {"external_per_side": "45", "initial_per_side": "27"}, Decimal("144")),
        ("machine_initial_total", {"added_total": "45", "initial_total": "37"}, Decimal("82")),
    ],
)
def test_pure_load_calculator_matches_machine_examples(mode, components, expected_lb):
    result = calculate_workout_load(mode, "lb", components)
    assert result.total_lb == expected_lb
    assert result.total_kg == expected_lb * LB_TO_KG
    assert result.details["components"] == {
        name: {"value": value, "unit": "lb"}
        for name, value in components.items()
    }
    assert result.details["calculation_version"] == "1.0"
    assert result.weight_kg == (expected_lb * LB_TO_KG).quantize(Decimal("0.01"))


def test_all_load_modes_and_assistance_semantics_are_explicit():
    cases = {
        "direct_total": {"direct_total": "40"},
        "per_side": {"per_side": "20"},
        "bar_plus_per_side": {"bar": "20", "per_side": "10"},
        "machine_initial_total": {"initial_total": "30", "added_total": "10"},
        "machine_initial_per_side": {"initial_per_side": "10", "external_per_side": "10"},
        "machine_external_per_side_initial_total": {"initial_total": "20", "external_per_side": "10"},
        "selector_stack": {"selector_stack": "40"},
        "dumbbell_each": {"dumbbell_each": "20"},
        "bodyweight": {"bodyweight": "80"},
        "bodyweight_plus": {"bodyweight": "80", "added_total": "10"},
        "assistance": {"bodyweight": "80", "assistance": "25"},
        "duration_distance": {"duration_seconds": "60", "distance_meters": "500"},
    }
    results = {mode: calculate_workout_load(mode, "kg", values) for mode, values in cases.items()}
    assert results["assistance"].total_kg == Decimal("55")
    assert results["assistance"].details["warnings"] == ["assistance_is_subtracted_from_bodyweight"]
    assert results["duration_distance"].weight_kg == 0
    with pytest.raises(WorkoutLoadError):
        calculate_workout_load("per_side", "kg", {"per_side": "10", "bar": "20"})
    with pytest.raises(WorkoutLoadError, match="does not match"):
        validate_load_details("99", results["direct_total"].details)


def test_mixed_component_units_are_preserved_and_calculated_once():
    components = {
        "bar": {"value": "20", "unit": "kg"},
        "per_side": {"value": "25", "unit": "lb"},
    }
    first = calculate_workout_load("bar_plus_per_side", "kg", components)
    second = calculate_workout_load("bar_plus_per_side", "kg", components)
    assert first.total_kg == Decimal("20") + Decimal("50") * LB_TO_KG
    assert first.details == second.details
    assert first.details["components"] == components
    assert first.details["original_input"]["components"] == components
    assert first.details["normalized_total_kg"] == "42.6796185"
    assert first.details["calculation_version"] == "1.0"
    with pytest.raises(WorkoutLoadError):
        calculate_workout_load("direct_total", "kg", {"direct_total": "-1"})
    with pytest.raises(WorkoutLoadError):
        calculate_workout_load("arbitrary", "kg", {"direct_total": "1"})


def test_web_load_entry_persists_detail_profile_and_user_unit(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        option = list_planned_days(user)[0]
        planned_day = option.key
    payload = {
        "planned_day": planned_day,
        "planned_workout_id": "",
        "client_submission_id": str(uuid.uuid4()),
        "performed_at": "2026-07-16T18:30",
        "preferred_load_unit": "lb",
        "exercise_0_remember_load": "1",
        "exercise_0_set_0_completed": "1",
        "exercise_0_set_0_load_mode": "machine_external_per_side_initial_total",
        "exercise_0_set_0_load_unit": "lb",
        "exercise_0_set_0_load_initial_total": "167",
        "exercise_0_set_0_load_initial_total_unit": "lb",
        "exercise_0_set_0_load_external_per_side": "115",
        "exercise_0_set_0_load_external_per_side_unit": "lb",
        "exercise_0_set_0_reps": "8",
    }
    response = client.post("/training-sessions/new", data=payload)
    assert response.status_code == 302
    with app.app_context():
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        profile = db.session.execute(db.select(ExerciseLoadProfile)).scalar_one()
        account = db.session.get(User, user)
        assert training_set.weight_kg == Decimal("180.08")
        assert training_set.load_details_json["calculated_total_lb"] == "397"
        assert training_set.load_details_json["calculation_version"] == "1.0"
        assert exercise_metrics(training_set.session_exercise)["volume"] == Decimal("1440.64")
        assert profile.user_id == user
        assert profile.load_mode == "machine_external_per_side_initial_total"
        assert profile.configuration_json["components"]["initial_total"] == {
            "value": "167", "unit": "lb"
        }
        assert profile.revision == 1
        assert account.preferred_load_unit == "lb"
        document = build_completed_workout_document(training_set.session_exercise.training_session, user)
        validate_json_document(document, "completed_workout")
        assert document["data"]["exercises"][0]["sets"][0]["load_details"]["original_unit"] == "lb"


def test_old_weight_only_post_stays_compatible(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key
    response = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day,
            "client_submission_id": str(uuid.uuid4()),
            "performed_at": "2026-07-16T19:00",
            "exercise_0_set_0_completed": "1",
            "exercise_0_set_0_weight_kg": "82.5",
            "exercise_0_set_0_reps": "7",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        assert training_set.weight_kg == Decimal("82.50")
        assert training_set.load_details_json["load_mode"] == "direct_total"
        assert training_set.load_details_json["components"] == {
            "direct_total": {"value": "82.5", "unit": "kg"}
        }


def test_web_load_entry_preserves_mixed_component_units(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key
    response = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day,
            "client_submission_id": str(uuid.uuid4()),
            "performed_at": "2026-07-16T19:15",
            "exercise_0_set_0_completed": "1",
            "exercise_0_set_0_load_mode": "bar_plus_per_side",
            "exercise_0_set_0_load_unit": "kg",
            "exercise_0_set_0_load_bar": "20",
            "exercise_0_set_0_load_bar_unit": "kg",
            "exercise_0_set_0_load_per_side": "25",
            "exercise_0_set_0_load_per_side_unit": "lb",
            "exercise_0_set_0_reps": "8",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        assert training_set.weight_kg == Decimal("42.68")
        assert training_set.load_details_json["components"] == {
            "bar": {"value": "20", "unit": "kg"},
            "per_side": {"value": "25", "unit": "lb"},
        }


def test_owner_can_edit_session_load_without_replacing_historical_identity(
    app, client, user
):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key
    submission_id = str(uuid.uuid4())
    created = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day,
            "client_submission_id": submission_id,
            "performed_at": "2026-07-16T18:30",
            "duration_minutes": "58",
            "exercise_0_set_0_completed": "1",
            "exercise_0_set_0_load_mode": "direct_total",
            "exercise_0_set_0_load_unit": "kg",
            "exercise_0_set_0_load_direct_total": "40",
            "exercise_0_set_0_load_direct_total_unit": "kg",
            "exercise_0_set_0_reps": "8",
        },
    )
    assert created.status_code == 302
    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        session_id = session.id
        session_public_id = session.public_id
        version_id = session.training_plan_version_id
        set_id = training_set.id
        source_file_id = session.source_file_id

    edit_page = client.get(f"/training-sessions/{session_id}/edit")
    assert edit_page.status_code == 200
    assert "Editar sesión".encode() in edit_page.data
    assert b"workout_session_drafts.js" not in edit_page.data
    assert b'name="exercise_0_set_0_load_direct_total" value="40"' in edit_page.data

    edited_form = {
        "planned_day": planned_day,
        "client_submission_id": submission_id,
        "performed_at": "2026-07-16T18:30",
        "duration_minutes": "58",
        "preferred_load_unit": "kg",
        "exercise_0_set_0_completed": "1",
        "exercise_0_set_0_load_mode": "bar_plus_per_side",
        "exercise_0_set_0_load_unit": "kg",
        "exercise_0_set_0_load_bar": "20",
        "exercise_0_set_0_load_bar_unit": "kg",
        "exercise_0_set_0_load_per_side": "25",
        "exercise_0_set_0_load_per_side_unit": "lb",
        "exercise_0_set_0_reps": "9",
        "exercise_0_set_0_rpe": "8.5",
    }
    edited = client.post(
        f"/training-sessions/{session_id}/edit", data=edited_form
    )
    assert edited.status_code == 302
    assert edited.headers["Location"].endswith(f"/training-sessions/{session_id}")
    replay = client.post(
        f"/training-sessions/{session_id}/edit", data=edited_form
    )
    assert replay.status_code == 302

    with app.app_context():
        session = db.session.get(TrainingSession, session_id)
        training_set = db.session.get(TrainingSet, set_id)
        assert session.public_id == session_public_id
        assert session.training_plan_version_id == version_id
        assert session.client_submission_id == submission_id
        assert session.revision == 2
        assert session.source_file_id != source_file_id
        assert training_set.id == set_id
        assert training_set.reps == 9
        assert training_set.rpe == Decimal("8.5")
        assert training_set.weight_kg == Decimal("42.68")
        assert training_set.load_details_json["components"] == {
            "bar": {"value": "20", "unit": "kg"},
            "per_side": {"value": "25", "unit": "lb"},
        }
        other = User(username="other-edit-user", role="user")
        other.set_password("fictional-password")
        db.session.add(other)
        db.session.commit()

    client.post("/logout")
    login(client, "other-edit-user", "fictional-password")
    assert client.get(f"/training-sessions/{session_id}/edit").status_code == 404


def test_advanced_load_fields_survive_form_render_and_are_idempotent(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key
    submission_id = str(uuid.uuid4())
    form = {
        "planned_day": planned_day, "client_submission_id": submission_id,
        "performed_at": "2026-07-16T20:00", "preferred_load_unit": "lb",
        "exercise_0_set_0_completed": "1", "exercise_0_set_0_load_mode": "per_side",
        "exercise_0_set_0_load_unit": "lb", "exercise_0_set_0_load_per_side": "45",
        "exercise_0_set_0_reps": "8",
    }
    first = client.post("/training-sessions/new", data=form)
    replay = client.post("/training-sessions/new", data=form)
    assert first.status_code == replay.status_code == 302
    form["exercise_0_set_0_load_per_side"] = "50"
    conflict = client.post("/training-sessions/new", data=form, follow_redirects=True)
    assert conflict.status_code == 200
    assert b"submission_conflict" in conflict.data
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(TrainingSet.id))).scalar_one() == 1


def test_mobile_load_ui_contains_all_modes_copy_and_draft_fields(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key
    page = client.get("/training-sessions/new", query_string={"planned_day": planned_day})
    assert page.status_code == 200
    for mode in (
        "direct_total", "per_side", "bar_plus_per_side", "machine_initial_total",
        "machine_initial_per_side", "machine_external_per_side_initial_total",
        "selector_stack", "dumbbell_each", "bodyweight", "bodyweight_plus",
        "assistance", "duration_distance",
    ):
        assert f'value="{mode}"'.encode() in page.data
    assert b"copy-load-sets" in page.data
    assert b"workout_load_entry.js" in page.data
    assert b"exercise_0_set_0_load_direct_total" in page.data
    assert b"exercise_0_set_0_load_direct_total_unit" in page.data
    script = (
        Path(__file__).parents[1] / "app" / "static" / "js" / "workout_load_entry.js"
    ).read_text(encoding="utf-8")
    assert 'if (raw === "") return null;' in script


def test_advanced_load_draft_allows_bounded_component_fields(app):
    with app.app_context():
        payload = {
            "schema_version": "1.0",
            "client_submission_id": str(uuid.uuid4()),
            "context": {
                "form_url": "/training-sessions/new?planned_day=fake",
                "plan_public_id": str(uuid.uuid4()),
                "training_plan_version_public_id": str(uuid.uuid4()),
                "planned_workout_public_id": None,
                "planned_week_number": 1,
                "planned_day_number": 1,
            },
            "fields": {f"exercise_0_set_{index}_load_component_{component}": "1" for index in range(100) for component in range(12)},
            "updated_at": "2026-07-16T12:00:00+00:00",
            "expires_at": "2099-07-16T12:00:00+00:00",
        }
        assert len(validate_draft_payload(payload)["fields"]) == 1200


def test_load_defaults_are_owner_scoped(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        other = User(username="other-load-user", role="user", preferred_load_unit="kg")
        other.set_password("fictional-password")
        db.session.add(other)
        db.session.commit()
        assert load_entry_defaults(other.id, ["Sentadilla"])["Sentadilla"] == {}


def test_load_profile_resolves_private_exercise_alias(app, user):
    with app.app_context():
        exercise = Exercise(user_id=user, canonical_name="Remo en T", normalized_name="remo en t")
        db.session.add(exercise)
        db.session.flush()
        db.session.add(ExerciseAlias(user_id=user, exercise_id=exercise.id, alias_name="T-bar row", normalized_name="t-bar row"))
        details = calculate_workout_load("machine_initial_total", "lb", {"initial_total": "37", "added_total": "45"}).details
        profile = upsert_exercise_load_profile(user_id=user, exercise_name="T-bar row", load_details=details)
        db.session.commit()
        assert profile.exercise_id == exercise.id
        defaults = load_entry_defaults(user, ["T-bar row"])
        assert defaults["T-bar row"]["profile"]["components"] == {
            "initial_total": {"value": "37", "unit": "lb"},
            "added_total": {"value": "45", "unit": "lb"},
        }


def test_load_profiles_round_trip_through_account_export_restore(app, user):
    with app.app_context():
        source = db.session.get(User, user)
        source.preferred_load_unit = "lb"
        details = calculate_workout_load("bar_plus_per_side", "lb", {"bar": "45", "per_side": "25"}).details
        upsert_exercise_load_profile(user_id=user, exercise_name="Press ficticio", load_details=details)
        target = User(username="load-restore-target", role="user")
        target.set_password("fictional-password")
        db.session.add(target)
        db.session.commit()
        target_id = target.id
        payload = build_user_data_document(source, user)
        preview = AccountRestoreService().preview(payload, user_id=target_id)
        result = AccountRestoreService().commit(
            payload, user_id=target_id, confirmation_token=preview["confirmation_token"]
        )
        restored = db.session.execute(
            db.select(ExerciseLoadProfile).where(ExerciseLoadProfile.user_id == target_id)
        ).scalar_one()
        assert result["committed"] is True
        assert restored.exercise.canonical_name == "Press ficticio"
        assert restored.configuration_json["components"] == {
            "bar": {"value": "45", "unit": "lb"},
            "per_side": {"value": "25", "unit": "lb"},
        }
        assert db.session.get(User, target_id).preferred_load_unit == "lb"


def test_mobile_schema_accepts_optional_load_details_without_requiring_it(app):
    details = calculate_workout_load("dumbbell_each", "lb", {"dumbbell_each": "25"}).details
    set_payload = {"set_number": 1, "planned_set_number": 1, "weight_kg": 22.68, "reps": 10, "load_details": details}
    document = {
        "schema_version": "1.0", "client_event_id": str(uuid.uuid4()),
        "started_at": "2026-07-16T12:00:00+00:00", "completed_at": "2026-07-16T13:00:00+00:00",
        "timezone": "UTC", "exercises": [{"exercise_order": 1, "planned_exercise_order": 1, "name": "Curl ficticio", "sets": [set_payload]}],
    }
    validate_json_document(document, "completed_workout_api")
    set_payload.pop("load_details")
    validate_json_document(document, "completed_workout_api")


def test_workout_load_migration_is_reversible_on_isolated_sqlite(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260716_0027_workout_load_entry.py"
    spec = importlib.util.spec_from_file_location("workout_load_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'workout-load.db'}")
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    exercises = sa.Table(
        "exercises", metadata, sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey(users.c.id)),
    )
    sa.Table(
        "training_sets", metadata, sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey(users.c.id)),
    )
    metadata.create_all(engine)
    try:
        for action in (migration.upgrade, migration.downgrade, migration.upgrade):
            with engine.begin() as connection:
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    action()
        inspector = sa.inspect(engine)
        assert "exercise_load_profiles" in inspector.get_table_names()
        assert "preferred_load_unit" in {item["name"] for item in inspector.get_columns("users")}
        assert "load_details_json" in {item["name"] for item in inspector.get_columns("training_sets")}
    finally:
        engine.dispose()
