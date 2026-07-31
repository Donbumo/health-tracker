from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import importlib.util
import io
import json
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event
import pytest
import sqlalchemy as sa
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from app.api_v1.rate_limit import rate_limiter
from app import create_app
from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    PlannedWorkout,
    ReminderEvent,
    ReminderRule,
    User,
    UserGoal,
    WeighIn,
)
from app.services.engagement import resolve_local_datetime
from tests.test_mobile_progress import _plan, _session
from tests.test_mobile_sync import _api_login, _auth


@pytest.fixture(autouse=True)
def clear_rate_limits():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def _headers(token, key=None):
    result = _auth(token)
    if key:
        result["Idempotency-Key"] = key
    return result


def _goal_payload(**changes):
    value = {
        "public_id": "91000000-0000-4000-8000-000000000001",
        "goal_type": "training_sessions_per_week",
        "target_value": "3",
        "unit": "session",
        "period": "weekly",
        "applicable_days": [1, 2, 3, 4, 5, 6, 7],
        "timezone": "America/Mexico_City",
        "start_date": "2026-07-27",
    }
    value.update(changes)
    return value


def _rule_payload(goal_id=None, **changes):
    value = {
        "public_id": "92000000-0000-4000-8000-000000000001",
        "reminder_type": "scheduled_workout_pending",
        "goal_public_id": goal_id,
        "local_time": "18:30",
        "applicable_days": [1, 3, 5],
        "lead_minutes": 15,
        "quiet_start": "22:00",
        "quiet_end": "07:00",
        "quiet_timezone": "America/Mexico_City",
        "snooze_options": [15, 30, 60, "tomorrow"],
        "max_per_day": 1,
        "cooldown_minutes": 120,
        "enabled": True,
        "timezone": "America/Mexico_City",
    }
    value.update(changes)
    return value


def _second_token(app, client):
    with app.app_context():
        account = User(username="engagement-other", role="user")
        account.set_password("fictional-password")
        db.session.add(account)
        db.session.commit()
    return _api_login(
        client, username="engagement-other", password="fictional-password",
        device_id="93000000-0000-4000-8000-000000000001",
    )["access_token"]


def test_empty_goal_crud_idempotency_revision_archive_and_owner_isolation(app, client, user):
    token = _api_login(client)["access_token"]
    assert client.get("/api/v1/mobile/goals", headers=_headers(token)).get_json()["data"]["items"] == []

    created = client.post("/api/v1/mobile/goals", json=_goal_payload(), headers=_headers(token, "goal-create"))
    replay = client.post("/api/v1/mobile/goals", json=_goal_payload(), headers=_headers(token, "goal-create"))
    assert created.status_code == replay.status_code == 201
    goal = created.get_json()["data"]
    assert goal["state"] == "active" and goal["revision"] == 1
    assert replay.get_json()["data"] == goal

    stale = client.patch(
        f"/api/v1/mobile/goals/{goal['public_id']}",
        json={"base_revision": 0, "state": "paused"}, headers=_headers(token, "goal-stale"),
    )
    assert stale.status_code == 409 and stale.get_json()["error"]["code"] == "revision_conflict"
    paused = client.patch(
        f"/api/v1/mobile/goals/{goal['public_id']}",
        json={"base_revision": 1, "state": "paused"}, headers=_headers(token, "goal-pause"),
    ).get_json()["data"]
    assert paused["state"] == "paused" and paused["revision"] == 2

    other = _second_token(app, client)
    assert client.get(f"/api/v1/mobile/goals/{goal['public_id']}", headers=_headers(other)).status_code == 404
    archived = client.delete(
        f"/api/v1/mobile/goals/{goal['public_id']}",
        json={"base_revision": 2}, headers=_headers(token, "goal-archive"),
    ).get_json()["data"]
    assert archived["state"] == "archived" and archived["revision"] == 3
    assert client.get("/api/v1/mobile/goals", headers=_headers(token)).get_json()["data"]["items"] == []


@pytest.mark.parametrize("changes,code", [
    ({"target_value": "0"}, "invalid_value"),
    ({"period": "monthly"}, "invalid_period"),
    ({"timezone": "Mars/Olympus"}, "invalid_timezone"),
    ({"unit": "kg"}, "invalid_goal_contract"),
    ({"applicable_days": [1, 1]}, "invalid_days"),
])
def test_goal_validation_is_structured(client, user, changes, code):
    token = _api_login(client)["access_token"]
    response = client.post(
        "/api/v1/mobile/goals", json=_goal_payload(**changes),
        headers=_headers(token, f"invalid-{code}"),
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code


def test_reminder_crud_quiet_hours_dedupe_snooze_acknowledgement_and_cross_access(app, client, user):
    token = _api_login(client)["access_token"]
    goal = client.post("/api/v1/mobile/goals", json=_goal_payload(), headers=_headers(token, "rule-goal")).get_json()["data"]
    assert client.get("/api/v1/mobile/reminder-rules", headers=_headers(token)).get_json()["data"]["items"] == []
    created = client.post(
        "/api/v1/mobile/reminder-rules", json=_rule_payload(goal["public_id"]),
        headers=_headers(token, "rule-create"),
    )
    assert created.status_code == 201
    rule = created.get_json()["data"]
    assert rule["quiet_start"] == "22:00" and rule["quiet_end"] == "07:00"
    assert rule["next_occurrence"] is not None

    disabled = client.patch(
        f"/api/v1/mobile/reminder-rules/{rule['public_id']}",
        json={"base_revision": 1, "enabled": False, "local_time": "19:00"},
        headers=_headers(token, "rule-disable"),
    ).get_json()["data"]
    assert disabled["enabled"] is False and disabled["next_occurrence"] is None
    enabled = client.patch(
        f"/api/v1/mobile/reminder-rules/{rule['public_id']}",
        json={"base_revision": 2, "enabled": True}, headers=_headers(token, "rule-enable"),
    ).get_json()["data"]

    now = datetime.now(timezone.utc).replace(microsecond=0)
    local_key = now.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="minutes")
    event_payload = {
        "public_id": "94000000-0000-4000-8000-000000000001",
        "rule_public_id": rule["public_id"], "scheduled_for": now.isoformat(),
        "scheduled_local": local_key, "event_type": rule["reminder_type"], "state": "triggered",
    }
    first = client.post("/api/v1/mobile/reminder-events", json=event_payload, headers=_headers(token, "event-one"))
    duplicate = client.post("/api/v1/mobile/reminder-events", json=event_payload, headers=_headers(token, "event-two"))
    assert first.status_code == 201 and duplicate.status_code == 200
    assert first.get_json()["data"]["public_id"] == duplicate.get_json()["data"]["public_id"]
    event_id = first.get_json()["data"]["public_id"]
    snoozed = client.patch(
        f"/api/v1/mobile/reminder-events/{event_id}",
        json={"base_revision": 1, "action": "snooze", "snoozed_until": (now + timedelta(minutes=30)).isoformat()},
        headers=_headers(token, "event-snooze"),
    ).get_json()["data"]
    assert snoozed["state"] == "snoozed"
    acknowledged = client.patch(
        f"/api/v1/mobile/reminder-events/{event_id}",
        json={"base_revision": 2, "action": "acknowledge"}, headers=_headers(token, "event-ack"),
    ).get_json()["data"]
    assert acknowledged["state"] == "acknowledged" and acknowledged["acknowledged_at"]
    other = _second_token(app, client)
    assert client.patch(
        f"/api/v1/mobile/reminder-events/{event_id}",
        json={"base_revision": 3, "action": "dismiss"}, headers=_headers(other, "foreign-event"),
    ).status_code == 404
    deleted = client.delete(
        f"/api/v1/mobile/reminder-rules/{rule['public_id']}",
        json={"base_revision": enabled["revision"]}, headers=_headers(token, "rule-delete"),
    )
    assert deleted.status_code == 200 and deleted.get_json()["data"]["deleted"] is True


def test_quiet_hours_and_rule_limits_are_validated(client, user):
    token = _api_login(client)["access_token"]
    missing_pair = client.post(
        "/api/v1/mobile/reminder-rules",
        json=_rule_payload(quiet_end=None), headers=_headers(token, "quiet-pair"),
    )
    assert missing_pair.status_code == 400 and missing_pair.get_json()["error"]["code"] == "invalid_quiet_hours"
    excessive = client.post(
        "/api/v1/mobile/reminder-rules",
        json=_rule_payload(max_per_day=11), headers=_headers(token, "rule-limit"),
    )
    assert excessive.status_code == 400 and excessive.get_json()["error"]["code"] == "invalid_limit"


def test_adherence_is_descriptive_bounded_and_reuses_health_targets(app, client, user):
    token = _api_login(client)["access_token"]
    payloads = [
        _goal_payload(),
        _goal_payload(public_id="91000000-0000-4000-8000-000000000002", goal_type="daily_steps", target_value="5000", unit="step", period="daily"),
        _goal_payload(public_id="91000000-0000-4000-8000-000000000003", goal_type="nutrition_protein", target_value="100", unit="g", period="daily"),
        _goal_payload(public_id="91000000-0000-4000-8000-000000000004", goal_type="weight_logging_frequency", target_value="1", unit="log", period="weekly"),
        _goal_payload(public_id="91000000-0000-4000-8000-000000000005", goal_type="scheduled_workouts_completion", target_value="1", unit="workout", period="scheduled_workouts"),
    ]
    for index, payload in enumerate(payloads):
        assert client.post("/api/v1/mobile/goals", json=payload, headers=_headers(token, f"adherence-goal-{index}")).status_code == 201
    with app.app_context():
        plan, version = _plan(user)
        _session(user, plan, version, datetime(2026, 7, 29, 18, tzinfo=timezone.utc))
        db.session.add_all([
            DailyEnergy(user_id=user, date=date(2026, 7, 29), steps=6000, source="manual"),
            DailyNutrition(user_id=user, date=date(2026, 7, 29), source="manual", protein_g=Decimal("110")),
            WeighIn(user_id=user, recorded_at=datetime(2026, 7, 29, 8, tzinfo=timezone.utc), weight_kg=Decimal("80"), source="manual"),
            PlannedWorkout(user_id=user, training_plan_id=plan.id, training_plan_version_id=version.id,
                scheduled_for_date=date(2026, 7, 29), timezone="America/Mexico_City", status="completed",
                title_snapshot="Entrenamiento QA", payload_snapshot_json={}, source_version=1),
        ])
        db.session.commit()

    statements = []
    def count_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(db.engine, "before_cursor_execute", count_sql)
    try:
        response = client.get(
            "/api/v1/mobile/adherence/summary?days=7&to=2026-07-31&timezone=America%2FMexico_City",
            headers=_headers(token),
        )
    finally:
        event.remove(db.engine, "before_cursor_execute", count_sql)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "available" and len(data["items"]) == 5
    # Authentication plus the fixed eager-loaded adherence query set must remain
    # bounded regardless of how many goals are evaluated.
    assert len(statements) <= 12
    sessions = next(item for item in data["items"] if item["goal"]["goal_type"] == "training_sessions_per_week")
    assert sessions["summary"].startswith("1 de 3") and "fall" not in json.dumps(data).lower()
    scheduled = next(item for item in data["items"] if item["goal"]["goal_type"] == "scheduled_workouts_completion")
    assert scheduled["completed"] == scheduled["expected"] == 1
    assert scheduled["comparison"]["percentage_change"] is None

    today = client.get(
        "/api/v1/mobile/health/today?date=2026-07-29&timezone=America%2FMexico_City",
        headers=_headers(token),
    ).get_json()["data"]
    assert today["steps"]["goal"] == 5000
    assert today["nutrition"]["targets"]["protein_g"] == "100"
    assert client.get("/api/v1/mobile/adherence/summary?days=8", headers=_headers(token)).status_code == 400


def test_adherence_without_goals_and_zero_denominator(client, user):
    token = _api_login(client)["access_token"]
    empty = client.get("/api/v1/mobile/adherence/summary?days=7&to=2026-07-31", headers=_headers(token)).get_json()["data"]
    assert empty == {
        "period": {"from": "2026-07-25", "to": "2026-07-31", "days": 7, "timezone": "UTC"},
        "status": "no_configured", "items": [], "summary": "No hay objetivos configurados.",
    }
    client.post(
        "/api/v1/mobile/goals",
        json=_goal_payload(goal_type="scheduled_workouts_completion", unit="workout", period="scheduled_workouts"),
        headers=_headers(token, "zero-denominator"),
    )
    item = client.get("/api/v1/mobile/adherence/summary?days=7&to=2026-07-31", headers=_headers(token)).get_json()["data"]["items"][0]
    assert item["expected"] == 0 and item["percentage"] is None and item["status"] == "insufficient_data"


def test_dst_resolution_preserves_local_intent_without_duplicate_overlap():
    gap = resolve_local_datetime(date(2026, 3, 8), time(2, 30), "America/New_York")
    assert gap.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%H:%M") == "03:30"
    overlap = resolve_local_datetime(date(2026, 11, 1), time(1, 30), "America/New_York")
    assert overlap.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).fold == 0
    no_dst = resolve_local_datetime(date(2026, 3, 8), time(2, 30), "America/Phoenix")
    assert no_dst.astimezone(__import__("zoneinfo").ZoneInfo("America/Phoenix")).strftime("%H:%M") == "02:30"


def test_engagement_responses_match_public_schemas(app, client, user):
    token = _api_login(client)["access_token"]
    goal = client.post("/api/v1/mobile/goals", json=_goal_payload(), headers=_headers(token, "schema-goal")).get_json()["data"]
    rule = client.post(
        "/api/v1/mobile/reminder-rules", json=_rule_payload(goal["public_id"]), headers=_headers(token, "schema-rule")
    ).get_json()["data"]
    adherence = client.get(
        "/api/v1/mobile/adherence/summary?days=7&to=2026-07-31&timezone=America%2FMexico_City",
        headers=_headers(token),
    ).get_json()["data"]
    root = Path(app.config["SCHEMA_ROOT"])
    goal_schema = json.loads((root / "mobile_goals.schema.json").read_text(encoding="utf-8"))
    rule_schema = json.loads((root / "mobile_reminder_rules.schema.json").read_text(encoding="utf-8"))
    adherence_schema = json.loads((root / "mobile_adherence.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(goal_schema, format_checker=FormatChecker()).validate(goal)
    Draft202012Validator(rule_schema, format_checker=FormatChecker()).validate(rule)
    registry = Registry().with_resource(goal_schema["$id"], Resource.from_contents(goal_schema))
    Draft202012Validator(adherence_schema, registry=registry, format_checker=FormatChecker()).validate(adherence)


def test_portable_goals_and_rules_round_trip_requires_device_confirmation(app, client, user):
    token = _api_login(client)["access_token"]
    goal = client.post("/api/v1/mobile/goals", json=_goal_payload(), headers=_headers(token, "portable-goal")).get_json()["data"]
    client.post("/api/v1/mobile/reminder-rules", json=_rule_payload(goal["public_id"]), headers=_headers(token, "portable-rule"))
    exported = client.post(
        "/api/v1/mobile/portability/exports", json={"sections": ["goals", "reminder_rules"]},
        headers=_headers(token, "portable-engagement-export"),
    ).get_json()["data"]
    package = client.get(
        f"/api/v1/mobile/portability/exports/{exported['export_id']}/download", headers=_headers(token)
    ).data
    other = _second_token(app, client)
    inspected = client.post(
        "/api/v1/mobile/portability/imports/inspect",
        data={"file": (io.BytesIO(package), "fictional-goals.htpack")},
        headers=_headers(other), content_type="multipart/form-data",
    )
    assert inspected.status_code == 201
    job = inspected.get_json()["data"]
    applied = client.post(
        f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
        json={"confirmed": True, "plan_revision": job["plan"]["revision"], "decisions": []},
        headers=_headers(other, "portable-engagement-apply"),
    )
    assert applied.status_code == 200
    with app.app_context():
        imported = db.session.execute(db.select(ReminderRule).where(ReminderRule.source == "portable_import")).scalar_one()
        assert imported.requires_device_confirmation is True
        assert imported.next_occurrence is None
        assert db.session.execute(db.select(ReminderEvent)).scalars().all() == []


def test_engagement_migration_0034_is_additive_reversible_and_reupgradeable(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260731_0034_goals_reminders_adherence.py"
    spec = importlib.util.spec_from_file_location("engagement_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'engagement-migration.db'}")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    inspector = sa.inspect(engine)
    assert {"user_goals", "reminder_rules", "reminder_events", "adherence_snapshots"} <= set(inspector.get_table_names())
    assert any(item["column_names"] == ["user_id", "deduplication_key"] for item in inspector.get_unique_constraints("reminder_events"))
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO user_goals (public_id,user_id,goal_type,target_value,unit,period,applicable_days_json,timezone,start_date,state,source,revision) "
            "VALUES ('95000000-0000-4000-8000-000000000001',1,'daily_steps',5000,'step','daily','[1,2,3,4,5,6,7]','UTC','2026-07-31','active','manual',1)"
        ))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    assert "user_goals" not in sa.inspect(engine).get_table_names()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    assert "reminder_rules" in sa.inspect(engine).get_table_names()
    engine.dispose()


@pytest.mark.skipif(not Path("/.dockerenv").exists(), reason="MariaDB engagement concurrency runs only in Docker")
def test_mariadb_goal_revision_and_event_dedupe_races(app, tmp_path):
    concurrent_app = create_app({
        "TESTING": True, "SECRET_KEY": "engagement-mariadb-secret-long-enough",
        "API_TOKEN_SIGNING_KEY": "engagement-mariadb-api-key-long-enough",
        "DATA_ROOT": tmp_path / "engagement-mariadb", "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC", "WTF_CSRF_ENABLED": False, "API_RATE_LIMIT_ENABLED": False,
    })
    username = f"engagement-race-{uuid.uuid4().hex}"
    with concurrent_app.app_context():
        account = User(username=username, email=f"{username}@example.invalid", role="user")
        account.set_password("fictional-race-password")
        db.session.add(account); db.session.commit(); user_id = account.id
    try:
        login = _api_login(concurrent_app.test_client(), username=f"{username}@example.invalid",
            password="fictional-race-password", device_id="93333333-3333-4333-8333-333333333333")
        token = login["access_token"]
        goal_payload = _goal_payload(public_id=str(uuid.uuid4()))
        barrier = Barrier(2)

        def create_goal_once():
            with concurrent_app.test_client() as race_client:
                barrier.wait(timeout=10)
                response = race_client.post("/api/v1/mobile/goals", json=goal_payload,
                    headers=_headers(token, "engagement-concurrent-goal"))
                return response.status_code, response.get_json()["data"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            created = list(pool.map(lambda _index: create_goal_once(), range(2)))
        assert [status for status, _data in created] == [201, 201]
        assert len({data["public_id"] for _status, data in created}) == 1
        with concurrent_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(UserGoal).where(UserGoal.user_id == user_id)) == 1

        client = concurrent_app.test_client()
        rule = client.post("/api/v1/mobile/reminder-rules", json=_rule_payload(goal_payload["public_id"], public_id=str(uuid.uuid4())),
            headers=_headers(token, "engagement-race-rule")).get_json()["data"]
        scheduled = datetime.now(timezone.utc) + timedelta(hours=1)
        event_barrier = Barrier(2)

        def create_event_once(index):
            payload = {
                "public_id": str(uuid.uuid4()), "rule_public_id": rule["public_id"],
                "scheduled_for": scheduled.isoformat(), "scheduled_local": "2026-07-31T18:30",
                "event_type": rule["reminder_type"], "state": "triggered",
            }
            with concurrent_app.test_client() as race_client:
                event_barrier.wait(timeout=10)
                response = race_client.post("/api/v1/mobile/reminder-events", json=payload,
                    headers=_headers(token, f"engagement-event-{index}"))
                return response.status_code, response.get_json()["data"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            events = list(pool.map(create_event_once, range(2)))
        assert sorted(status for status, _data in events) == [200, 201]
        assert len({data["public_id"] for _status, data in events}) == 1
        with concurrent_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(ReminderEvent).where(ReminderEvent.user_id == user_id)) == 1

        patch_barrier = Barrier(2)
        def patch_once(state, key):
            with concurrent_app.test_client() as race_client:
                patch_barrier.wait(timeout=10)
                return race_client.patch(f"/api/v1/mobile/goals/{goal_payload['public_id']}",
                    json={"base_revision": 1, "state": state}, headers=_headers(token, key)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda args: patch_once(*args), [("paused", "goal-patch-a"), ("completed", "goal-patch-b")]))
        assert sorted(statuses) == [200, 409]
    finally:
        with concurrent_app.app_context():
            account = db.session.get(User, user_id)
            if account is not None: db.session.delete(account)
            db.session.commit()
