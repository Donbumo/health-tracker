import json
import importlib.util
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import create_app
from app.extensions import db
from app.models import (
    SyncChange,
    PlannedWorkout,
    TrainingSession,
    TrainingSet,
    User,
    UploadedFile,
    WorkoutSessionDraft,
)
from app.services.workout_drafts import payload_hash, validate_draft_payload
from app.services.workout_sessions import list_planned_days
from app.services.workout_sessions import create_manual_training_session
from app.services.mobile_sync import PlannedWorkoutService
from app.services.exporters.user_data import build_user_data_document
from app.services.validation import validate_json_document
from app.services.importers.standard_import_executor import StandardImportExecutor
from tests.test_phase_3 import training_plan_document
from tests.conftest import login
from tests.test_phase_4 import _import_plan


def _hidden(response, name: str) -> str:
    match = re.search(
        rf'name="{name}"[^>]*value="([^"]*)"'.encode(), response.data
    )
    assert match is not None
    return match.group(1).decode()


def _full_form(planned_day: str, submission_id: str) -> dict[str, str]:
    return {
        "planned_day": planned_day,
        "planned_workout_id": "",
        "client_submission_id": submission_id,
        "performed_at": "2026-07-15T18:30",
        "duration_minutes": "245",
        "average_heart_rate_bpm": "143",
        "calories_burned": "678.25",
        "notes": "Fictional long workout notes",
        "preferred_load_unit": "lb",
        "exercise_0_set_0_completed": "1",
        "exercise_0_set_0_weight_kg": "82.50",
        "exercise_0_set_0_load_mode": "machine_initial_total",
        "exercise_0_set_0_load_unit": "lb",
        "exercise_0_set_0_load_initial_total": "37",
        "exercise_0_set_0_load_added_total": "45",
        "exercise_0_remember_load": "1",
        "exercise_0_set_0_reps": "7",
        "exercise_0_set_0_rir": "1.5",
        "exercise_0_set_0_rpe": "9.0",
        "exercise_0_set_0_rest_seconds": "180",
        "exercise_0_set_0_notes": "Fictional recovered set note",
    }


def _context(app, user_id: int):
    with app.app_context():
        option = list_planned_days(user_id)[0]
        return {
            "planned_day": option.key,
            "plan_public_id": option.plan.public_id,
            "version_public_id": option.version.public_id,
            "week": option.week["week_number"],
            "day": option.day["day_number"],
        }


def _draft_payload(context: dict, submission_id: str, **fields):
    return {
        "schema_version": "1.0",
        "client_submission_id": submission_id,
        "context": {
            "form_url": (
                "/training-sessions/new?planned_day=" + context["planned_day"]
            ),
            "plan_public_id": context["plan_public_id"],
            "training_plan_version_public_id": context["version_public_id"],
            "planned_workout_public_id": None,
            "planned_week_number": context["week"],
            "planned_day_number": context["day"],
        },
        "fields": fields or {"notes": "Fictional draft"},
        "updated_at": "2026-07-15T12:00:00+00:00",
        "expires_at": "2099-07-22T12:00:00+00:00",
    }


def test_expired_csrf_recovers_every_workout_field_and_second_submit_saves_once(
    app, client, user, caplog
):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    app.config["WTF_CSRF_ENABLED"] = True
    page = client.get(
        "/training-sessions/new", query_string={"planned_day": context["planned_day"]}
    )
    original_token = _hidden(page, "csrf_token")
    submission_id = _hidden(page, "client_submission_id")
    form = _full_form(context["planned_day"], submission_id)
    form["csrf_token"] = original_token

    app.config["WTF_CSRF_TIME_LIMIT"] = -1
    recovered = client.post("/training-sessions/new", data=form)
    assert recovered.status_code == 422
    assert (
        "El token de seguridad venció. Recuperamos todos tus datos; "
        "vuelve a presionar Guardar.".encode()
        in recovered.data
    )
    assert _hidden(recovered, "csrf_token") != original_token
    assert _hidden(recovered, "client_submission_id") == submission_id
    for value in (
        "2026-07-15T18:30",
        "245",
        "143",
        "678.25",
        "Fictional long workout notes",
        "82.50",
        "machine_initial_total",
        "37",
        "45",
        "7",
        "1.5",
        "9.0",
        "180",
        "Fictional recovered set note",
    ):
        assert value.encode() in recovered.data
    assert b'exercise_0_set_0_completed" value="1" checked' in recovered.data
    assert "Fictional long workout notes" not in caplog.text
    assert "82.50" not in caplog.text
    with app.app_context():
        assert db.session.execute(db.select(TrainingSession)).scalar_one_or_none() is None

    app.config["WTF_CSRF_TIME_LIMIT"] = 8 * 60 * 60
    form["csrf_token"] = _hidden(recovered, "csrf_token")
    saved = client.post("/training-sessions/new", data=form)
    assert saved.status_code == 302
    assert "?" not in saved.headers["Location"]
    assert submission_id not in saved.headers["Location"]
    replay = client.post("/training-sessions/new", data=form)
    assert replay.status_code == 302
    assert replay.headers["Location"] == saved.headers["Location"]
    detail = client.get(saved.headers["Location"])
    assert detail.status_code == 200
    assert b' id="completed-workout-submission"' in detail.data
    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        assert session.client_submission_id == submission_id
        assert session.duration_seconds == 245 * 60
        assert session.average_heart_rate_bpm == 143
        assert str(session.calories_burned) == "678.25"
        assert training_set.reps == 7
        assert str(training_set.rir) == "1.5"
        assert str(training_set.rpe) == "9.0"
        assert training_set.rest_seconds == 180
        assert training_set.notes == "Fictional recovered set note"
        assert db.session.execute(
            db.select(db.func.count(SyncChange.sequence)).where(
                SyncChange.entity_type == "completed_workout"
            )
        ).scalar_one() == 1


def test_expired_csrf_recovers_owned_session_edit_without_early_write(
    app, client, user
):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    submission_id = str(uuid.uuid4())
    original_form = _full_form(context["planned_day"], submission_id)
    created = client.post("/training-sessions/new", data=original_form)
    assert created.status_code == 302
    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        session_id = session.id
        original_revision = session.revision

    app.config["WTF_CSRF_ENABLED"] = True
    page = client.get(f"/training-sessions/{session_id}/edit")
    original_token = _hidden(page, "csrf_token")
    edited_form = dict(original_form)
    edited_form.update(
        csrf_token=original_token,
        exercise_0_set_0_load_initial_total="40",
        exercise_0_set_0_load_added_total="50",
        exercise_0_set_0_reps="8",
        notes="Fictional recovered edit",
    )
    app.config["WTF_CSRF_TIME_LIMIT"] = -1
    recovered = client.post(
        f"/training-sessions/{session_id}/edit", data=edited_form
    )
    assert recovered.status_code == 422
    assert b"Guardar cambios" in recovered.data
    assert b"Fictional recovered edit" in recovered.data
    assert b'name="exercise_0_set_0_load_initial_total" value="40"' in recovered.data
    assert _hidden(recovered, "csrf_token") != original_token
    with app.app_context():
        session = db.session.get(TrainingSession, session_id)
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        assert session.revision == original_revision
        assert training_set.reps == 7

    app.config["WTF_CSRF_TIME_LIMIT"] = 8 * 60 * 60
    edited_form["csrf_token"] = _hidden(recovered, "csrf_token")
    saved = client.post(
        f"/training-sessions/{session_id}/edit", data=edited_form
    )
    assert saved.status_code == 302
    with app.app_context():
        session = db.session.get(TrainingSession, session_id)
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        assert session.revision == original_revision + 1
        assert training_set.reps == 8


def test_same_submission_with_changed_payload_is_a_safe_conflict(app, client, user):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    submission_id = str(uuid.uuid4())
    form = _full_form(context["planned_day"], submission_id)
    assert client.post("/training-sessions/new", data=form).status_code == 302
    form["exercise_0_set_0_reps"] = "8"
    conflict = client.post(
        "/training-sessions/new", data=form, follow_redirects=True
    )
    assert conflict.status_code == 200
    assert b"submission_conflict" in conflict.data
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(TrainingSession.id))).scalar_one() == 1


def test_planned_workout_completion_and_sync_are_atomic_and_not_duplicated(
    app, client, user
):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        option = list_planned_days(user)[0]
        planned = PlannedWorkoutService.schedule_from_plan_version(
            user_id=user,
            plan_public_id=option.plan.public_id,
            version_public_id=option.version.public_id,
            scheduled_for_date=date(2026, 7, 15),
            timezone_name="UTC",
            week_number=option.week["week_number"],
            day_number=option.day["day_number"],
        )
        db.session.commit()
        planned_public_id = planned.public_id
    page = client.get(
        "/training-sessions/new",
        query_string={"planned_workout_id": planned_public_id},
    )
    planned_day = _hidden(page, "planned_day")
    submission_id = _hidden(page, "client_submission_id")
    form = _full_form(planned_day, submission_id)
    form["planned_workout_id"] = planned_public_id
    first = client.post("/training-sessions/new", data=form)
    second = client.post("/training-sessions/new", data=form)
    assert first.status_code == second.status_code == 302
    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        planned = db.session.execute(db.select(PlannedWorkout)).scalar_one()
        assert session.planned_workout_id == planned.id
        assert planned.status == "completed"
        assert planned.completed_at is not None
        assert db.session.execute(
            db.select(db.func.count(SyncChange.sequence)).where(
                SyncChange.entity_type == "completed_workout"
            )
        ).scalar_one() == 1

    conflicting_id = str(uuid.uuid4())
    conflicting = dict(form)
    conflicting["client_submission_id"] = conflicting_id
    conflict = client.post(
        "/training-sessions/new", data=conflicting, follow_redirects=True
    )
    assert conflict.status_code == 200
    assert b"submission_conflict" in conflict.data
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(TrainingSession.id))).scalar_one() == 1
        assert db.session.execute(db.select(db.func.count(UploadedFile.id))).scalar_one() == 2


def test_account_export_preserves_submission_id_without_exposing_internal_hash(
    app, client, user
):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    submission_id = str(uuid.uuid4())
    client.post(
        "/training-sessions/new",
        data=_full_form(context["planned_day"], submission_id),
    )
    with app.app_context():
        document = build_user_data_document(db.session.get(User, user), user)
        validate_json_document(document, "user_data_export")
        workout = document["data"]["training_sessions"][0]
        assert workout["data"]["client_submission_id"] == submission_id
        assert "client_payload_sha256" not in json.dumps(workout)


def test_draft_payload_hash_size_and_unsafe_fields(app, user):
    context = {
        "planned_day": "1:0:0",
        "plan_public_id": str(uuid.uuid4()),
        "version_public_id": str(uuid.uuid4()),
        "week": 1,
        "day": 1,
    }
    payload = _draft_payload(context, str(uuid.uuid4()), notes="Fictional")
    with app.app_context():
        clean = validate_draft_payload(payload)
        assert payload_hash(clean) == payload_hash(json.loads(json.dumps(clean)))
        unsafe = json.loads(json.dumps(payload))
        unsafe["fields"]["csrf_token"] = "forbidden"
        try:
            validate_draft_payload(unsafe)
        except ValueError as error:
            assert "unsafe" in str(error)
        else:
            raise AssertionError("unsafe draft field was accepted")


def test_server_draft_crud_revision_csrf_and_owner_isolation(app, client, user):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    submission_id = str(uuid.uuid4())
    payload = _draft_payload(context, submission_id, notes="Fictional server draft")
    created = client.post("/workout-session-drafts", json={"payload": payload})
    assert created.status_code == 201
    envelope = created.get_json()["data"]
    public_id = envelope["public_id"]
    assert envelope["revision"] == 1
    detail = client.get(f"/workout-session-drafts/{public_id}")
    assert detail.status_code == 200
    assert detail.get_json()["data"]["payload"]["fields"]["notes"] == "Fictional server draft"
    restored_page = client.get(
        "/training-sessions/new",
        query_string={"planned_day": context["planned_day"]},
    )
    assert b'id="server-workout-draft"' in restored_page.data
    assert b"Fictional server draft" in restored_page.data

    payload["fields"]["notes"] = "Fictional updated draft"
    updated = client.patch(
        f"/workout-session-drafts/{public_id}",
        json={"payload": payload, "revision": 1},
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["revision"] == 2
    stale = client.patch(
        f"/workout-session-drafts/{public_id}",
        json={"payload": payload, "revision": 1},
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "draft_conflict"

    with app.app_context():
        other = User(username="draft-other", role="user")
        other.set_password("draft-other-password")
        db.session.add(other)
        db.session.commit()
    client.post("/logout")
    login(client, "draft-other", "draft-other-password")
    assert client.get(f"/workout-session-drafts/{public_id}").status_code == 404
    assert client.delete(f"/workout-session-drafts/{public_id}").status_code == 404

    app.config["WTF_CSRF_ENABLED"] = True
    denied = client.post("/workout-session-drafts", json={"payload": payload})
    assert denied.status_code == 403
    assert denied.get_json()["error"]["code"] == "csrf_failed"


def test_server_draft_rejects_oversized_payload(app, client, user):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    payload = _draft_payload(
        context, str(uuid.uuid4()), notes="Fictional " + ("x" * 1000)
    )
    app.config["WORKOUT_DRAFT_MAX_BYTES"] = 256
    response = client.post("/workout-session-drafts", json={"payload": payload})
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "draft_too_large"
    with app.app_context():
        assert db.session.execute(db.select(WorkoutSessionDraft)).scalar_one_or_none() is None


def test_successful_session_deletes_server_draft_but_failed_session_keeps_it(
    app, client, user
):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    submission_id = str(uuid.uuid4())
    payload = _draft_payload(context, submission_id, notes="Fictional retained draft")
    assert client.post("/workout-session-drafts", json={"payload": payload}).status_code == 201
    invalid = _full_form(context["planned_day"], submission_id)
    invalid["exercise_0_set_0_reps"] = ""
    assert client.post("/training-sessions/new", data=invalid).status_code == 200
    with app.app_context():
        assert db.session.execute(db.select(WorkoutSessionDraft)).scalar_one() is not None
    valid = _full_form(context["planned_day"], submission_id)
    assert client.post("/training-sessions/new", data=valid).status_code == 302
    with app.app_context():
        assert db.session.execute(db.select(WorkoutSessionDraft)).scalar_one_or_none() is None


def test_login_session_lifetime_csrf_lifetime_and_stable_secret(app, client, user):
    response = login(client)
    assert response.status_code == 302
    with client.session_transaction() as web_session:
        assert web_session.permanent is True
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=12)
    assert app.config["WTF_CSRF_TIME_LIMIT"] == 8 * 60 * 60
    assert app.config["SESSION_REFRESH_EACH_REQUEST"] is True
    assert app.config["SECRET_KEY"] == "test-secret-key-that-is-long-enough"


def test_missing_short_and_placeholder_secret_keys_fail_at_startup(app):
    base = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_ENGINE_OPTIONS": {},
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC",
    }
    for secret in (None, "short", "replace-with-a-long-random-secret"):
        try:
            create_app({**base, "SECRET_KEY": secret})
        except RuntimeError as error:
            assert "SECRET_KEY" in str(error)
        else:
            raise AssertionError("insecure SECRET_KEY was accepted")


def test_workout_draft_javascript_contract(client, user):
    login(client)
    script = client.get("/static/js/workout_session_drafts.js")
    assert script.status_code == 200
    for contract in (
        b"health-tracker:v1:workout-draft:",
        b"LOCAL_DEBOUNCE_MS = 500",
        b"localStorage",
        b"draft_restored",
        b"draft_too_large",
        b"X-CSRFToken",
        b"client_submission_id",
    ):
        assert contract in script.data
    assert b"Authorization" not in script.data


def test_workout_draft_cleanup_is_dry_run_by_default(app, client, user):
    login(client)
    _import_plan(client, user)
    context = _context(app, user)
    payload = _draft_payload(context, str(uuid.uuid4()), notes="Fictional cleanup")
    client.post("/workout-session-drafts", json={"payload": payload})
    with app.app_context():
        draft = db.session.execute(db.select(WorkoutSessionDraft)).scalar_one()
        draft.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        public_id = draft.public_id
        db.session.commit()
    expired = client.get(f"/workout-session-drafts/{public_id}")
    assert expired.status_code == 410
    assert expired.get_json()["error"]["code"] == "draft_expired"
    runner = app.test_cli_runner()
    dry_run = runner.invoke(args=["workout-drafts", "cleanup"])
    assert dry_run.exit_code == 0
    assert "mode=dry-run" in dry_run.output
    assert "expired_drafts=1" in dry_run.output
    assert "records_deleted=0" in dry_run.output
    with app.app_context():
        assert db.session.execute(db.select(WorkoutSessionDraft)).scalar_one() is not None
    applied = runner.invoke(args=["workout-drafts", "cleanup", "--apply"])
    assert applied.exit_code == 0
    assert "records_deleted=1" in applied.output
    with app.app_context():
        assert db.session.execute(db.select(WorkoutSessionDraft)).scalar_one_or_none() is None


def test_workout_recovery_migration_is_reversible_on_isolated_sqlite(tmp_path):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260715_0026_workout_session_recovery.py"
    )
    spec = importlib.util.spec_from_file_location("workout_recovery_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'workout-recovery.db'}")
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    plans = sa.Table(
        "training_plans",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey(users.c.id)),
    )
    versions = sa.Table(
        "training_plan_versions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_plan_id", sa.Integer(), sa.ForeignKey(plans.c.id)),
    )
    api_devices = sa.Table("api_devices", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    planned = sa.Table(
        "planned_workouts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey(users.c.id)),
    )
    sa.Table(
        "training_sessions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
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
        assert "workout_session_drafts" in inspector.get_table_names()
        assert "client_submission_id" in {
            item["name"] for item in inspector.get_columns("training_sessions")
        }
        unique_names = {
            item["name"] for item in inspector.get_unique_constraints("training_sessions")
        }
        assert "uq_training_sessions_user_submission" in unique_names
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not Path("/.dockerenv").exists(),
    reason="MariaDB double-submit race runs only in the Docker suite",
)
def test_mariadb_concurrent_web_submission_creates_exactly_one_session(app, tmp_path):
    username = f"workout-race-{uuid.uuid4().hex}"
    concurrent_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "workout-race-secret-key-long-enough",
            "API_TOKEN_SIGNING_KEY": "workout-race-api-key-long-enough",
            "DATA_ROOT": tmp_path / "workout-race",
            "UPLOAD_ROOT": tmp_path / "workout-race" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "workout-race" / "generated",
            "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
            "APP_TIMEZONE": "UTC",
            "WTF_CSRF_ENABLED": False,
            "API_RATE_LIMIT_ENABLED": False,
        }
    )
    with concurrent_app.app_context():
        account = User(username=username, role="user")
        account.set_password("fictional-race-password")
        db.session.add(account)
        db.session.commit()
        user_id = account.id
    try:
        with concurrent_app.app_context():
            StandardImportExecutor().commit_documents(
                [training_plan_document(user_id)],
                user_id=user_id,
                target_type="training_plan",
                confirmed=True,
            )
        submission_id = str(uuid.uuid4())
        barrier = Barrier(2)

        def save_once():
            with concurrent_app.app_context():
                planned_day = list_planned_days(user_id)[0]
                planned_exercise = planned_day.day["exercises"][0]
                planned_set = planned_exercise["sets"][0]
                exercises = [{
                    "exercise_order": 1,
                    "planned_exercise_order": planned_exercise["exercise_order"],
                    "name": planned_exercise["name"],
                    "sets": [{
                        "set_number": 1,
                        "planned_set_number": planned_set["set_number"],
                        "weight_kg": 70,
                        "reps": 6,
                    }],
                }]
                barrier.wait(timeout=10)
                record, duplicate = create_manual_training_session(
                    user_id=user_id,
                    planned_day=planned_day,
                    performed_at=datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc),
                    exercises=exercises,
                    client_submission_id=submission_id,
                )
                return record.public_id, duplicate

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: save_once(), range(2)))
        assert len({item[0] for item in results}) == 1
        assert sorted(item[1] for item in results) == [False, True]
        with concurrent_app.app_context():
            assert db.session.execute(
                db.select(db.func.count(TrainingSession.id)).where(
                    TrainingSession.user_id == user_id,
                    TrainingSession.client_submission_id == submission_id,
                )
            ).scalar_one() == 1
    finally:
        with concurrent_app.app_context():
            account = db.session.get(User, user_id)
            if account is not None:
                db.session.delete(account)
                db.session.commit()
