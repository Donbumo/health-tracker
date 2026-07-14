import copy
import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.api_v1.rate_limit import rate_limiter
from app import create_app
from app.extensions import db
from app.models import (
    ApiDevice,
    DeviceSyncState,
    IdempotencyRecord,
    PlannedWorkout,
    SyncChange,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    User,
)
from app.services.mobile_sync import encode_cursor


DEVICE_ID = "71111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _api_login(client, username="test-user", password="test-password", device_id=DEVICE_ID):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": username,
            "password": password,
            "device": {
                "device_id": device_id,
                "name": "Móvil QA ficticio",
                "platform": "android",
                "app_version": "0.7.0",
                "os_version": "QA",
            },
        },
    )
    assert response.status_code == 200
    return response.get_json()["data"]


def _add_plan(app, user_id, name="Plan sync ficticio"):
    document = {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {
            "name": name,
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Fuerza A ficticia",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Sentadilla ficticia",
                                    "sets": [
                                        {"set_number": 1, "reps": 5, "rest_seconds": 120},
                                        {"set_number": 2, "reps": 5, "rest_seconds": 120},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }
    with app.app_context():
        plan = TrainingPlan(user_id=user_id, name=name, active_version_number=1)
        db.session.add(plan)
        db.session.flush()
        version = TrainingPlanVersion(
            user_id=user_id,
            training_plan=plan,
            version_number=1,
            schema_version="1.0",
            sha256="7" * 64,
            content=document,
        )
        db.session.add(version)
        db.session.commit()
        return plan.public_id, version.public_id


def _schedule_payload(plan_id, version_id):
    return {
        "training_plan_id": plan_id,
        "training_plan_version_id": version_id,
        "scheduled_for_date": "2026-08-01",
        "timezone": "America/Mexico_City",
        "week_number": 1,
        "day_number": 1,
    }


def _completed_payload(planned_id, event_id=None):
    return {
        "schema_version": "1.0",
        "client_event_id": event_id or str(uuid.uuid4()),
        "planned_workout_id": planned_id,
        "started_at": "2026-08-01T12:00:00Z",
        "completed_at": "2026-08-01T12:45:00Z",
        "timezone": "America/Mexico_City",
        "duration_seconds": 2700,
        "average_heart_rate_bpm": 126,
        "calories_burned": 321.5,
        "notes": "Sesión ficticia para QA",
        "client_updated_at": "2026-08-01T12:46:00Z",
        "exercises": [
            {
                "exercise_order": 1,
                "planned_exercise_order": 1,
                "name": "Sentadilla ficticia",
                "sets": [
                    {
                        "set_number": 1,
                        "planned_set_number": 1,
                        "weight_kg": 50,
                        "reps": 5,
                        "rir": 2,
                        "rpe": 8,
                        "rest_seconds": 120,
                    },
                    {
                        "set_number": 2,
                        "planned_set_number": 2,
                        "weight_kg": 50,
                        "reps": 5,
                        "rir": 1,
                        "rpe": 9,
                        "rest_seconds": 150,
                    },
                ],
            }
        ],
    }


def _create_planned(client, headers, plan_id, version_id, key="planned-create-1"):
    response = client.post(
        "/api/v1/planned-workouts",
        json=_schedule_payload(plan_id, version_id),
        headers={**headers, "Idempotency-Key": key},
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def test_planned_workout_snapshot_revision_idempotency_and_historical_version(
    app, client, user
):
    plan_id, version_id = _add_plan(app, user)
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    payload = _schedule_payload(plan_id, version_id)
    first = client.post(
        "/api/v1/planned-workouts",
        json=payload,
        headers={**headers, "Idempotency-Key": "same-planned-key"},
    )
    replay = client.post(
        "/api/v1/planned-workouts",
        json=payload,
        headers={**headers, "Idempotency-Key": "same-planned-key"},
    )
    assert first.status_code == replay.status_code == 201
    created = first.get_json()["data"]
    assert replay.get_json()["data"] == created
    assert created["revision"] == 1
    detail_payload = client.get(
        f"/api/v1/planned-workouts/{created['id']}", headers=headers
    ).get_json()["data"]
    assert detail_payload["training_plan_version_id"] == version_id
    assert detail_payload["snapshot"]["day"]["name"] == "Fuerza A ficticia"
    with app.app_context():
        assert db.session.execute(db.select(PlannedWorkout)).scalars().all().__len__() == 1
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        plan.active_version_number = 2
        version = TrainingPlanVersion(
            user_id=user,
            training_plan=plan,
            version_number=2,
            schema_version="1.0",
            sha256="8" * 64,
            content={**copy.deepcopy(plan.versions[0].content), "user_id": user},
        )
        version.content["data"]["weeks"][0]["days"][0]["name"] = "Día cambiado"
        db.session.add(version)
        db.session.commit()
    detail = client.get(f"/api/v1/planned-workouts/{created['id']}", headers=headers)
    assert detail.get_json()["data"]["snapshot"]["day"]["name"] == "Fuerza A ficticia"


def test_planned_transitions_revision_conflict_and_cross_user_404(app, client, user):
    plan_id, version_id = _add_plan(app, user)
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    created = _create_planned(client, headers, plan_id, version_id)
    started = client.post(
        f"/api/v1/planned-workouts/{created['id']}/start",
        json={"base_revision": 1},
        headers={**headers, "Idempotency-Key": "start-1"},
    )
    assert started.status_code == 200
    assert started.get_json()["data"]["status"] == "in_progress"
    assert started.get_json()["data"]["revision"] == 2
    stale = client.patch(
        f"/api/v1/planned-workouts/{created['id']}",
        json={"base_revision": 1, "scheduled_for_date": "2026-08-02", "timezone": "UTC"},
        headers={**headers, "Idempotency-Key": "stale-1"},
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"]["details"]["server_revision"] == 2
    with app.app_context():
        other = User(username="sync-other", email="sync-other@example.test", role="user")
        other.set_password("other-password")
        db.session.add(other)
        db.session.commit()
    other_tokens = _api_login(
        client,
        username="sync-other@example.test",
        password="other-password",
        device_id="72222222-2222-4222-8222-222222222222",
    )
    assert client.get(
        f"/api/v1/planned-workouts/{created['id']}",
        headers=_auth(other_tokens["access_token"]),
    ).status_code == 404


def test_completed_workout_maps_full_session_completes_plan_and_is_idempotent(
    app, client, user
):
    plan_id, version_id = _add_plan(app, user)
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    planned = _create_planned(client, headers, plan_id, version_id)
    payload = _completed_payload(planned["id"])
    created = client.post(
        "/api/v1/completed-workouts",
        json=payload,
        headers={**headers, "Idempotency-Key": "completed-1"},
    )
    assert created.status_code == 201
    data = created.get_json()["data"]
    assert data["planned_workout_id"] == planned["id"]
    detail = client.get(
        f"/api/v1/completed-workouts/{data['id']}", headers=headers
    ).get_json()["data"]
    assert detail["duration_seconds"] == 2700
    assert detail["average_heart_rate_bpm"] == 126
    assert detail["calories_burned"] == 321.5
    assert detail["exercises"][0]["sets"][1]["rpe"] == 9
    assert detail["exercises"][0]["sets"][1]["rest_seconds"] == 150
    replay_event = client.post(
        "/api/v1/completed-workouts",
        json=payload,
        headers={**headers, "Idempotency-Key": "completed-2"},
    )
    assert replay_event.status_code == 200
    assert replay_event.get_json()["data"]["duplicate"] is True
    changed = copy.deepcopy(payload)
    changed["notes"] = "Contenido distinto"
    conflict = client.post(
        "/api/v1/completed-workouts",
        json=changed,
        headers={**headers, "Idempotency-Key": "completed-3"},
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["error"]["code"] == "event_conflict"
    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        planned_record = db.session.execute(db.select(PlannedWorkout)).scalar_one()
        assert session.public_id == data["id"]
        assert session.source_device.public_device_id == DEVICE_ID
        assert planned_record.status == "completed"
        assert session.training_plan_version.public_id == version_id


def test_sync_bootstrap_pull_pagination_filter_tombstone_and_foreign_cursor(
    app, client, user
):
    plan_id, version_id = _add_plan(app, user)
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    first = _create_planned(client, headers, plan_id, version_id, "planned-a")
    second = _create_planned(client, headers, plan_id, version_id, "planned-b")
    with app.app_context():
        device = db.session.execute(db.select(ApiDevice)).scalar_one()
        zero = encode_cursor(user, device.id, 0)
    pull_one = client.get(f"/api/v1/sync/pull?cursor={zero}&limit=1", headers=headers)
    assert pull_one.status_code == 200
    assert len(pull_one.get_json()["data"]["changes"]) == 1
    assert pull_one.get_json()["data"]["has_more"] is True
    next_cursor = pull_one.get_json()["data"]["next_cursor"]
    pull_two = client.get(
        f"/api/v1/sync/pull?cursor={next_cursor}&limit=10&entity_types=planned_workout",
        headers=headers,
    )
    assert pull_two.status_code == 200
    assert [item["entity_id"] for item in pull_two.get_json()["data"]["changes"]] == [second["id"]]
    bootstrap = client.get("/api/v1/sync/bootstrap", headers=headers)
    assert bootstrap.status_code == 200
    assert bootstrap.get_json()["data"]["capabilities"]["incremental_pull"] is True
    assert len(bootstrap.get_json()["data"]["planned_workouts"]) == 2
    with app.app_context():
        foreign_cursor = encode_cursor(user + 999, 999, 0)
    assert client.get(
        f"/api/v1/sync/pull?cursor={foreign_cursor}", headers=headers
    ).status_code == 400
    delete_payload = {
        "schema_version": "1.0",
        "batch_id": str(uuid.uuid4()),
        "operations": [{
            "client_operation_id": str(uuid.uuid4()),
            "entity_type": "planned_workout",
            "operation": "delete",
            "entity_id": first["id"],
            "base_revision": 1,
            "payload": {},
        }],
    }
    deleted = client.post(
        "/api/v1/sync/push",
        json=delete_payload,
        headers={**headers, "Idempotency-Key": "delete-batch"},
    )
    assert deleted.status_code == 200
    cursor_before_delete = bootstrap.get_json()["data"]["cursor"]
    tombstones = client.get(
        f"/api/v1/sync/pull?cursor={cursor_before_delete}", headers=headers
    ).get_json()["data"]["changes"]
    assert tombstones[-1]["operation"] == "delete"
    assert tombstones[-1]["payload"] is None


def test_sync_push_partial_results_replay_conflict_and_unsupported(app, client, user):
    plan_id, version_id = _add_plan(app, user)
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    operation_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())
    payload = {
        "schema_version": "1.0",
        "batch_id": str(uuid.uuid4()),
        "operations": [
            {
                "client_operation_id": operation_id,
                "entity_type": "planned_workout",
                "operation": "upsert",
                "entity_id": entity_id,
                "payload": _schedule_payload(plan_id, version_id),
            },
            {
                "client_operation_id": str(uuid.uuid4()),
                "entity_type": "daily_energy",
                "operation": "upsert",
                "entity_id": str(uuid.uuid4()),
                "payload": {},
            },
        ],
    }
    first = client.post(
        "/api/v1/sync/push",
        json=payload,
        headers={**headers, "Idempotency-Key": "push-key-1"},
    )
    assert first.status_code == 200
    statuses = [item["status"] for item in first.get_json()["data"]["results"]]
    assert statuses == ["accepted", "unsupported"]
    replay = client.post(
        "/api/v1/sync/push",
        json=payload,
        headers={**headers, "Idempotency-Key": "push-key-1"},
    )
    assert replay.status_code == 200
    changed = copy.deepcopy(payload)
    changed["batch_id"] = str(uuid.uuid4())
    assert client.post(
        "/api/v1/sync/push",
        json=changed,
        headers={**headers, "Idempotency-Key": "push-key-1"},
    ).status_code == 409
    second_batch = copy.deepcopy(payload)
    second_batch["batch_id"] = str(uuid.uuid4())
    second_batch["operations"] = [second_batch["operations"][0]]
    duplicate = client.post(
        "/api/v1/sync/push",
        json=second_batch,
        headers={**headers, "Idempotency-Key": "push-key-2"},
    )
    assert duplicate.get_json()["data"]["results"][0]["status"] == "duplicate"
    with app.app_context():
        assert db.session.execute(db.select(PlannedWorkout)).scalars().all().__len__() == 1


def test_mobile_sync_schemas_status_cli_web_and_persistence(app, client, user):
    plan_id, version_id = _add_plan(app, user)
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    planned = _create_planned(client, headers, plan_id, version_id)
    status = client.get("/api/v1/sync/status", headers=headers)
    assert status.status_code == 200
    schema_root = app.config["SCHEMA_ROOT"]
    documents = {
        "planned_workout": client.get(
            f"/api/v1/planned-workouts/{planned['id']}", headers=headers
        ).get_json()["data"],
        "completed_workout_api": _completed_payload(planned["id"]),
        "sync_bootstrap": client.get("/api/v1/sync/bootstrap", headers=headers).get_json()["data"],
        "sync_status": status.get_json()["data"],
        "sync_pull": client.get(
            f"/api/v1/sync/pull?cursor={status.get_json()['data']['cursor']}",
            headers=headers,
        ).get_json()["data"],
        "sync_push": {
            "schema_version": "1.0",
            "batch_id": str(uuid.uuid4()),
            "operations": [{
                "client_operation_id": str(uuid.uuid4()),
                "entity_type": "planned_workout",
                "operation": "delete",
                "entity_id": planned["id"],
                "base_revision": 1,
                "payload": {},
            }],
        },
    }
    for name, document in documents.items():
        schema = json.loads((schema_root / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    web = client.get("/planned-workouts")
    assert web.status_code == 200
    assert b"planned-workouts/new" in web.data
    assert planned["id"].encode() in web.data
    with app.app_context():
        db.session.remove()
    with app.app_context():
        persisted = db.session.execute(db.select(PlannedWorkout)).scalar_one()
        assert persisted.public_id == planned["id"]
        assert db.session.execute(db.select(DeviceSyncState)).scalar_one()
        assert db.session.execute(db.select(IdempotencyRecord)).scalars().first()
        stored_responses = json.dumps([
            item.response_body_json
            for item in db.session.execute(db.select(IdempotencyRecord)).scalars()
        ])
        assert "snapshot" not in stored_responses
        assert "Sesión ficticia" not in stored_responses
        assert db.session.execute(db.select(SyncChange)).scalars().first()
    runner = app.test_cli_runner()
    dry = runner.invoke(args=["mobile-sync", "cleanup"])
    assert dry.exit_code == 0
    assert "mode=dry-run" in dry.output


def test_mobile_sync_requires_bearer_and_idempotency_and_rejects_cookie(client, app, user):
    plan_id, version_id = _add_plan(app, user)
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    payload = _schedule_payload(plan_id, version_id)
    assert client.get("/api/v1/sync/status").status_code == 401
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    missing = client.post("/api/v1/planned-workouts", json=payload, headers=headers)
    assert missing.status_code == 400
    assert missing.get_json()["error"]["code"] == "idempotency_required"
    assert client.get(
        f"/api/v1/sync/status?access_token={tokens['access_token']}"
    ).status_code == 401


def test_mobile_sync_engine_isolation_keeps_sqlite_compatible(app, tmp_path):
    sqlite_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "mobile-sync-sqlite-compat-secret-long-enough",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "DATA_ROOT": tmp_path / "sqlite-compat",
            "UPLOAD_ROOT": tmp_path / "sqlite-compat" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "sqlite-compat" / "generated",
            "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
            "APP_TIMEZONE": "UTC",
        }
    )
    assert "isolation_level" not in sqlite_app.config["SQLALCHEMY_ENGINE_OPTIONS"]
    with sqlite_app.app_context():
        db.create_all()
        db.session.add(User(username="sqlite-sync-user", password_hash="fixture"))
        db.session.commit()
        assert db.session.execute(db.select(User)).scalar_one().username == "sqlite-sync-user"
        db.drop_all()


def test_planned_workout_web_requires_csrf_and_is_owner_only(app, client, user):
    plan_id, version_id = _add_plan(app, user)
    tokens = _api_login(client)
    planned = _create_planned(
        client, _auth(tokens["access_token"]), plan_id, version_id
    )
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    app.config["WTF_CSRF_ENABLED"] = True
    page = client.get("/planned-workouts")
    token = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', page.data).group(1).decode()
    denied = client.post(f"/planned-workouts/{planned['id']}/skip")
    assert denied.status_code == 400
    allowed = client.post(
        f"/planned-workouts/{planned['id']}/skip",
        data={"csrf_token": token},
    )
    assert allowed.status_code == 302
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        other = User(username="web-owner-other", role="user")
        other.set_password("other-password")
        db.session.add(other)
        db.session.commit()
    client.post("/logout")
    client.post("/login", data={"username": "web-owner-other", "password": "other-password"})
    assert client.post(f"/planned-workouts/{planned['id']}/cancel").status_code == 404


@pytest.mark.skipif(
    not Path("/.dockerenv").exists(),
    reason="MariaDB concurrency contract runs only in the Docker suite",
)
def test_mariadb_idempotency_client_operation_and_revision_races(app, tmp_path):
    username = f"sync-race-{uuid.uuid4().hex}"
    concurrent_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "mobile-sync-mariadb-test-secret-long-enough",
            "API_TOKEN_SIGNING_KEY": "mobile-sync-mariadb-api-key-long-enough",
            "DATA_ROOT": tmp_path / "mariadb-sync",
            "UPLOAD_ROOT": tmp_path / "mariadb-sync" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "mariadb-sync" / "generated",
            "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
            "APP_TIMEZONE": "UTC",
            "WTF_CSRF_ENABLED": False,
            "API_RATE_LIMIT_ENABLED": False,
        }
    )
    with concurrent_app.app_context():
        account = User(username=username, email=f"{username}@example.test", role="user")
        account.set_password("race-test-password")
        db.session.add(account)
        db.session.commit()
        user_id = account.id
    try:
        plan_id, version_id = _add_plan(concurrent_app, user_id, "Plan carrera sync")
        login_data = _api_login(
            concurrent_app.test_client(),
            username=f"{username}@example.test",
            password="race-test-password",
            device_id="73333333-3333-4333-8333-333333333333",
        )
        headers = _auth(login_data["access_token"])
        payload = _schedule_payload(plan_id, version_id)
        barrier = Barrier(2)

        def create_once():
            with concurrent_app.test_client() as race_client:
                barrier.wait(timeout=10)
                response = race_client.post(
                    "/api/v1/planned-workouts",
                    json=payload,
                    headers={**headers, "Idempotency-Key": "mariadb-shared-key"},
                )
                return response.status_code, response.get_json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            create_results = list(pool.map(lambda _index: create_once(), range(2)))
        assert [item[0] for item in create_results] == [201, 201]
        public_ids = {item[1]["data"]["id"] for item in create_results}
        assert len(public_ids) == 1
        public_id = public_ids.pop()
        with concurrent_app.app_context():
            assert db.session.execute(
                db.select(db.func.count(PlannedWorkout.id)).where(
                    PlannedWorkout.user_id == user_id
                )
            ).scalar_one() == 1

        patch_barrier = Barrier(2)

        def patch_once(day, key):
            with concurrent_app.test_client() as race_client:
                patch_barrier.wait(timeout=10)
                response = race_client.patch(
                    f"/api/v1/planned-workouts/{public_id}",
                    json={
                        "base_revision": 1,
                        "scheduled_for_date": day,
                        "timezone": "UTC",
                    },
                    headers={**headers, "Idempotency-Key": key},
                )
                return response.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            patch_results = list(
                pool.map(
                    lambda args: patch_once(*args),
                    [("2026-08-02", "race-patch-a"), ("2026-08-03", "race-patch-b")],
                )
            )
        assert sorted(patch_results) == [200, 409]

        operation_id = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        operation = {
            "client_operation_id": operation_id,
            "entity_type": "planned_workout",
            "operation": "upsert",
            "entity_id": entity_id,
            "payload": payload,
        }
        operation_barrier = Barrier(2)

        def push_once(index):
            batch = {
                "schema_version": "1.0",
                "batch_id": str(uuid.uuid4()),
                "operations": [operation],
            }
            with concurrent_app.test_client() as race_client:
                operation_barrier.wait(timeout=10)
                response = race_client.post(
                    "/api/v1/sync/push",
                    json=batch,
                    headers={**headers, "Idempotency-Key": f"operation-race-{index}"},
                )
                return response.status_code, response.get_json()["data"]["results"][0]["status"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            operation_results = list(pool.map(push_once, range(2)))
        assert sorted(status for _code, status in operation_results) == ["accepted", "duplicate"]
        assert {code for code, _status in operation_results} == {200}
        with concurrent_app.app_context():
            assert db.session.execute(
                db.select(db.func.count(PlannedWorkout.id)).where(
                    PlannedWorkout.user_id == user_id
                )
            ).scalar_one() == 2
    finally:
        with concurrent_app.app_context():
            account = db.session.get(User, user_id)
            if account is not None:
                db.session.delete(account)
                db.session.commit()
