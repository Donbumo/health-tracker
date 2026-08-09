from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator, FormatChecker
import sqlalchemy as sa
from sqlalchemy import event

from app.extensions import db
from app.models import (
    Exercise,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    User,
)
from tests.test_mobile_sync import _api_login, _auth
from app.services.mobile_progress import history_page


def test_exercise_public_id_migration_is_reversible_on_sqlite(tmp_path):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260724_0029_exercise_public_ids.py"
    )
    spec = importlib.util.spec_from_file_location(
        "exercise_public_id_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'exercise-public-ids.db'}")
    metadata = sa.MetaData()
    exercises = sa.Table(
        "exercises",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
    )
    occurrences = sa.Table(
        "training_session_exercises",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(exercises.insert(), [{"name": "Ejercicio QA"}])
        connection.execute(occurrences.insert(), [{"name": "Serie QA"}])

    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()

        inspector = sa.inspect(engine)
        for table_name in ("exercises", "training_session_exercises"):
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }
            assert columns["public_id"]["nullable"] is False
            constraints = inspector.get_unique_constraints(table_name)
            assert any(item["column_names"] == ["public_id"] for item in constraints)
            with engine.connect() as connection:
                public_id = connection.execute(
                    sa.text(f"SELECT public_id FROM {table_name}")
                ).scalar_one()
            assert len(public_id) == 36

        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.downgrade()
        inspector = sa.inspect(engine)
        assert "public_id" not in {
            column["name"] for column in inspector.get_columns("exercises")
        }
        assert "public_id" not in {
            column["name"]
            for column in inspector.get_columns("training_session_exercises")
        }
    finally:
        engine.dispose()


def _plan(user_id: int, name: str = "Plan móvil ficticio"):
    plan = TrainingPlan(user_id=user_id, name=name, active_version_number=1)
    db.session.add(plan)
    db.session.flush()
    version = TrainingPlanVersion(
        user_id=user_id,
        training_plan=plan,
        version_number=1,
        schema_version="1.0",
        sha256=(str(user_id)[-1:] or "1") * 64,
        content={"schema_version": "1.0", "data": {"weeks": []}},
    )
    db.session.add(version)
    db.session.flush()
    return plan, version


def _session(
    user_id: int,
    plan,
    version,
    when: datetime,
    *,
    exercise_name: str = "Sentadilla móvil ficticia",
    weight: str = "50",
    reps: int = 5,
    load_mode: str = "direct_total",
):
    identity = db.session.execute(
        db.select(Exercise).where(
            Exercise.user_id == user_id,
            Exercise.normalized_name == exercise_name.casefold(),
        )
    ).scalar_one_or_none()
    if identity is None:
        identity = Exercise(
            user_id=user_id,
            canonical_name=exercise_name,
            normalized_name=exercise_name.casefold(),
        )
        db.session.add(identity)
        db.session.flush()
    record = TrainingSession(
        user_id=user_id,
        training_plan=plan,
        training_plan_version=version,
        performed_at=when,
        started_at=when - timedelta(minutes=40),
        completed_at=when,
        timezone="UTC",
        planned_week_number=1,
        planned_day_number=1,
        duration_seconds=2400,
        notes="Nota ficticia de QA",
    )
    db.session.add(record)
    db.session.flush()
    exercise = TrainingSessionExercise(
        user_id=user_id,
        training_session=record,
        exercise_order=1,
        planned_exercise_order=1,
        name=exercise_name,
        notes="Ejercicio ficticio",
    )
    db.session.add(exercise)
    db.session.flush()
    details = None if load_mode == "direct_total" else {"load_mode": load_mode}
    db.session.add(
        TrainingSet(
            user_id=user_id,
            session_exercise=exercise,
            set_number=1,
            planned_set_number=1,
            weight_kg=Decimal(weight),
            load_details_json=details,
            reps=reps,
            rir=Decimal("2"),
            rpe=Decimal("8"),
            rest_seconds=90,
            notes="Serie ficticia",
        )
    )
    db.session.flush()
    return record, identity


def _headers(client):
    return _auth(_api_login(client)["access_token"])


def test_mobile_history_empty_and_limits(client, user):
    headers = _headers(client)
    response = client.get("/api/v1/mobile/history", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["items"] == []
    assert client.get("/api/v1/mobile/history?limit=0", headers=headers).status_code == 400
    assert client.get("/api/v1/mobile/history?limit=101", headers=headers).status_code == 400


def test_mobile_history_cursor_filters_detail_and_cross_user_404(app, client, user):
    now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    with app.app_context():
        plan, version = _plan(user)
        oldest, identity = _session(user, plan, version, now - timedelta(days=3), weight="40")
        middle, _ = _session(user, plan, version, now - timedelta(days=2), weight="50")
        newest, _ = _session(user, plan, version, now - timedelta(days=1), weight="60")
        other = User(username="mobile-progress-other", email="progress-other@example.test", role="user")
        other.set_password("other-password")
        db.session.add(other)
        db.session.flush()
        other_plan, other_version = _plan(other.id, "Plan ajeno ficticio")
        foreign, _ = _session(other.id, other_plan, other_version, now, exercise_name="Ejercicio ajeno")
        db.session.commit()
        identity_id = identity.public_id
        newest_id = newest.public_id
        middle_id = middle.public_id
        oldest_id = oldest.public_id
        foreign_id = foreign.public_id

    headers = _headers(client)
    first = client.get("/api/v1/mobile/history?limit=2", headers=headers).get_json()["data"]
    assert [item["public_id"] for item in first["items"]] == [newest_id, middle_id]
    assert first["has_more"] is True
    with app.app_context():
        plan = db.session.execute(db.select(TrainingPlan).where(TrainingPlan.user_id == user)).scalar_one()
        version = plan.versions[0]
        _session(user, plan, version, now + timedelta(hours=1), weight="70")
        db.session.commit()
    second = client.get(
        "/api/v1/mobile/history",
        query_string={"limit": 2, "cursor": first["next_cursor"]},
        headers=headers,
    ).get_json()["data"]
    assert [item["public_id"] for item in second["items"]] == [oldest_id]
    filtered = client.get(
        "/api/v1/mobile/history",
        query_string={
            "date_from": "2026-07-22",
            "date_to": "2026-07-23",
            "exercise_public_id": identity_id,
        },
        headers=headers,
    ).get_json()["data"]["items"]
    assert [item["public_id"] for item in filtered] == [newest_id, middle_id]
    detail = client.get(f"/api/v1/mobile/history/{newest_id}", headers=headers).get_json()["data"]
    assert detail["volume_kg"] == "300.00"
    assert detail["exercises"][0]["exercise_public_id"] == identity_id
    assert detail["exercises"][0]["sets"][0]["notes"] == "Serie ficticia"
    assert client.get(f"/api/v1/mobile/history/{foreign_id}", headers=headers).status_code == 404
    assert client.get("/api/v1/mobile/history/not-a-uuid", headers=headers).status_code == 404


def test_progress_ranges_previous_zero_modes_and_personal_records(app, client, user):
    now = datetime.now(timezone.utc)
    with app.app_context():
        plan, version = _plan(user)
        first, identity = _session(user, plan, version, now - timedelta(days=5), weight="50", reps=5)
        second, _ = _session(user, plan, version, now - timedelta(days=2), weight="60", reps=6)
        _session(
            user,
            plan,
            version,
            now - timedelta(days=1),
            exercise_name="Carrera móvil ficticia",
            weight="0",
            reps=1,
            load_mode="duration_distance",
        )
        db.session.commit()
        identity_id = identity.public_id
        second_id = second.public_id

    headers = _headers(client)
    for value in ("7", "30", "90", "180", "365", "all"):
        response = client.get(f"/api/v1/mobile/progress/summary?range={value}", headers=headers)
        assert response.status_code == 200
    summary = client.get("/api/v1/mobile/progress/summary?range=7", headers=headers).get_json()["data"]
    assert summary["metrics"]["sessions"] == 3
    assert summary["metrics"]["volume_kg"] == "610.00"
    assert summary["metrics"]["volume_partial"] is True
    assert summary["comparison"]["sessions"]["percent"] is None
    listing = client.get("/api/v1/mobile/progress/exercises?range=30", headers=headers).get_json()["data"]
    squat = next(item for item in listing["items"] if item["public_id"] == identity_id)
    assert squat["best_load_kg"] == "60.00"
    assert squat["trend"] == "up"
    detail = client.get(
        f"/api/v1/mobile/progress/exercises/{identity_id}?range=30", headers=headers
    ).get_json()["data"]
    assert len(detail["points"]) == 2
    records = {item["type"]: item for item in detail["personal_records"]}
    assert records["highest_load"]["value"] == "60.00"
    assert records["highest_load"]["session_public_id"] == second_id
    assert records["highest_set_volume"]["value"] == "360.00"
    assert records["highest_session_volume"]["value"] == "360.00"
    assert client.get("/api/v1/mobile/progress/summary?range=8", headers=headers).status_code == 400


def test_progress_mixed_load_modes_are_explicitly_not_comparable(app, client, user):
    now = datetime.now(timezone.utc)
    with app.app_context():
        plan, version = _plan(user)
        _, identity = _session(user, plan, version, now - timedelta(days=2), weight="50")
        _session(user, plan, version, now - timedelta(days=1), weight="55", load_mode="bodyweight_plus")
        db.session.commit()
        identity_id = identity.public_id
    headers = _headers(client)
    detail = client.get(
        f"/api/v1/mobile/progress/exercises/{identity_id}?range=30", headers=headers
    ).get_json()["data"]
    assert detail["exercise"]["load_comparable"] is False
    assert detail["exercise"]["best_load_kg"] is None
    assert detail["exercise"]["volume_partial"] is True


def test_mobile_history_and_progress_responses_match_public_schemas(app, client, user):
    now = datetime.now(timezone.utc)
    with app.app_context():
        plan, version = _plan(user)
        record, identity = _session(user, plan, version, now - timedelta(days=1))
        db.session.commit()
        session_id = record.public_id
        exercise_id = identity.public_id
        schema_root = app.config["SCHEMA_ROOT"]
        history_schema = json.loads((schema_root / "mobile_history.schema.json").read_text(encoding="utf-8"))
        progress_schema = json.loads((schema_root / "mobile_progress.schema.json").read_text(encoding="utf-8"))
    headers = _headers(client)
    documents = [
        (history_schema, client.get("/api/v1/mobile/history", headers=headers).get_json()["data"]),
        (history_schema, client.get(f"/api/v1/mobile/history/{session_id}", headers=headers).get_json()["data"]),
        (progress_schema, client.get("/api/v1/mobile/progress/summary?range=30", headers=headers).get_json()["data"]),
        (progress_schema, client.get("/api/v1/mobile/progress/exercises?range=30", headers=headers).get_json()["data"]),
        (progress_schema, client.get(f"/api/v1/mobile/progress/exercises/{exercise_id}?range=30", headers=headers).get_json()["data"]),
    ]
    for schema, document in documents:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_history_query_count_is_bounded_instead_of_n_plus_one(app, user):
    now = datetime.now(timezone.utc)
    with app.app_context():
        plan, version = _plan(user)
        for day in range(5):
            _session(user, plan, version, now - timedelta(days=day))
        db.session.commit()
        statements = []

        def count_query(*_args):
            statements.append(1)

        event.listen(db.engine, "before_cursor_execute", count_query)
        try:
            page = history_page(user_id=user, limit=5)
        finally:
            event.remove(db.engine, "before_cursor_execute", count_query)
        assert len(page["items"]) == 5
        assert len(statements) <= 8
