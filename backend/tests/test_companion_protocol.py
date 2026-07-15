import copy
import importlib.util
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator, FormatChecker

from app.api_v1.rate_limit import rate_limiter
from app import create_app
from app.extensions import db
from app.models import (
    ApiDevice,
    CompanionDeviceProfile,
    CompanionProgressEvent,
    CompanionWorkoutDelivery,
    PlannedWorkout,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    User,
)
from app.services.mobile_sync import canonical_hash


DEVICE_ID = "81111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def clear_limiter():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, username="test-user", password="test-password", device_id=DEVICE_ID):
    response = client.post("/api/v1/auth/login", json={
        "email": username,
        "password": password,
        "device": {
            "device_id": device_id,
            "name": "Companion QA ficticio",
            "platform": "android",
            "app_version": "0.8.0",
            "os_version": "QA",
        },
    })
    assert response.status_code == 200
    return response.get_json()["data"]


def _plan(app, user_id):
    document = {
        "schema_version": "1.0", "record_type": "training_plan",
        "user_id": user_id, "source_type": "manual_generated",
        "data": {"name": "Plan companion ficticio", "weeks": [{
            "week_number": 1, "days": [{
                "day_number": 1, "name": "Día companion ficticio",
                "exercises": [{
                    "exercise_order": 1, "name": "Sentadilla ficticia",
                    "notes": "Nota ficticia limitada",
                    "sets": [
                        {"set_number": 1, "reps": 5, "rest_seconds": 120},
                        {"set_number": 2, "reps_min": 5, "reps_max": 7, "rest_seconds": 150},
                    ],
                }],
            }],
        }]},
    }
    with app.app_context():
        plan = TrainingPlan(user_id=user_id, name=document["data"]["name"], active_version_number=1)
        db.session.add(plan)
        db.session.flush()
        version = TrainingPlanVersion(
            user_id=user_id, training_plan=plan, version_number=1,
            schema_version="1.0", sha256="a" * 64, content=document,
        )
        db.session.add(version)
        db.session.commit()
        return plan.public_id, version.public_id


def _planned(client, headers, plan_id, version_id):
    response = client.post("/api/v1/planned-workouts", headers={**headers, "Idempotency-Key": "planned-companion"}, json={
        "training_plan_id": plan_id,
        "training_plan_version_id": version_id,
        "scheduled_for_date": "2026-08-20",
        "timezone": "America/Mexico_City",
        "week_number": 1,
        "day_number": 1,
    })
    assert response.status_code == 201
    return response.get_json()["data"]


def _negotiate(client, headers, *, features=None, metrics=None, base_revision=None):
    payload = {
        "schema_version": "1.0",
        "protocol_versions": ["1.0"],
        "workout_schema_versions": ["1.0"],
        "result_schema_versions": ["1.0"],
        "features": features or ["offline", "rest_timer", "rpe", "rir", "weight", "heart_rate_summary", "calories_summary"],
        "metrics": metrics or ["reps", "weight_kg", "rest_seconds", "rpe", "rir", "average_heart_rate_bpm", "calories_burned"],
        "limits": {"max_payload_bytes": 65536, "max_progress_events_per_workout": 50},
    }
    if base_revision is not None:
        payload["base_revision"] = base_revision
    return client.post("/api/v1/companion/negotiate", headers=headers, json=payload)


def _delivery(client, headers, planned_id, key="delivery-1"):
    response = client.post(
        "/api/v1/companion/deliveries",
        headers={**headers, "Idempotency-Key": key},
        json={"schema_version": "1.0", "planned_workout_id": planned_id},
    )
    assert response.status_code in {200, 201}
    return response.get_json()["data"]


def _operation(client, headers, delivery, action, revision, **extra):
    payload = {
        "schema_version": "1.0",
        "client_operation_id": str(uuid.uuid4()),
        "base_revision": revision,
        **extra,
    }
    return client.post(
        f"/api/v1/companion/deliveries/{delivery['id']}/{action}",
        headers={**headers, "Idempotency-Key": f"{action}-{payload['client_operation_id']}"},
        json=payload,
    )


def _setup(client, app, user, *, features=None):
    plan_id, version_id = _plan(app, user)
    tokens = _login(client)
    headers = _auth(tokens["access_token"])
    negotiated = _negotiate(client, headers, features=features)
    assert negotiated.status_code == 201
    planned = _planned(client, headers, plan_id, version_id)
    delivery = _delivery(client, headers, planned["id"])
    return headers, planned, delivery


def _result(planned_id, event_id):
    return {
        "schema_version": "1.0",
        "client_event_id": event_id,
        "planned_workout_id": planned_id,
        "started_at": "2026-08-20T12:00:00Z",
        "completed_at": "2026-08-20T12:45:00Z",
        "timezone": "America/Mexico_City",
        "duration_seconds": 2700,
        "average_heart_rate_bpm": 125,
        "calories_burned": 300,
        "exercises": [{
            "exercise_order": 1, "planned_exercise_order": 1,
            "name": "Sentadilla ficticia",
            "sets": [
                {"set_number": 1, "planned_set_number": 1, "weight_kg": 50, "reps": 5, "rir": 2, "rpe": 8, "rest_seconds": 120},
                {"set_number": 2, "planned_set_number": 2, "weight_kg": 50, "reps": 6, "rir": 1, "rpe": 9, "rest_seconds": 150},
            ],
        }],
    }


def test_profile_negotiation_allowlists_versions_revision_and_persistence(app, client, user):
    tokens = _login(client)
    headers = _auth(tokens["access_token"])
    response = _negotiate(client, headers, features=["offline", "rest_timer", "future_feature"], metrics=["reps", "future_metric"])
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["selected_protocol_version"] == "1.0"
    assert data["accepted_features"] == ["offline", "rest_timer"]
    assert data["rejected_features"] == ["future_feature"]
    assert data["rejected_metrics"] == ["future_metric"]
    assert data["profile"]["revision"] == 1
    assert client.get("/api/v1/companion/profile", headers=headers).status_code == 200
    stale = _negotiate(client, headers, base_revision=7)
    assert stale.status_code == 409
    updated = _negotiate(client, headers, base_revision=1)
    assert updated.status_code == 200
    assert updated.get_json()["data"]["profile"]["revision"] == 2
    incompatible = copy.deepcopy({
        "schema_version": "1.0", "protocol_versions": ["2.0"],
        "workout_schema_versions": ["1.0"], "result_schema_versions": ["1.0"],
        "features": ["offline"], "metrics": ["reps"], "limits": {}, "base_revision": 2,
    })
    denied = client.post("/api/v1/companion/negotiate", headers=headers, json=incompatible)
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "companion_protocol_unsupported"
    with app.app_context():
        profile = db.session.execute(db.select(CompanionDeviceProfile)).scalar_one()
        assert profile.public_id == data["profile"]["id"]


def test_package_is_snapshot_deterministic_for_delivery_and_reports_dropped_fields(app, client, user):
    headers, planned, delivery = _setup(client, app, user, features=["offline"])
    package_a = client.get(f"/api/v1/companion/deliveries/{delivery['id']}/package", headers=headers).get_json()["data"]
    package_b = client.get(f"/api/v1/companion/deliveries/{delivery['id']}/package", headers=headers).get_json()["data"]
    assert package_a == package_b
    stored_hash = package_a["package_hash"]
    unhashed = dict(package_a)
    unhashed.pop("package_hash")
    assert canonical_hash(unhashed) == stored_hash
    assert package_a["unsupported_fields"] == [
        "exercises[0].sets[0].rest_seconds", "exercises[0].sets[1].rest_seconds"
    ]
    assert "rest_seconds" not in package_a["exercises"][0]["sets"][0]
    replay = _delivery(client, headers, planned["id"], key="delivery-2")
    assert replay["id"] == delivery["id"]
    assert replay["duplicate"] is True
    with app.app_context():
        record = db.session.execute(db.select(PlannedWorkout)).scalar_one()
        assert record.payload_snapshot_json["day"]["exercises"][0]["sets"][0]["rest_seconds"] == 120


def test_delivery_ack_start_progress_sequence_duplicate_and_terminal_protection(app, client, user):
    headers, _planned_data, delivery = _setup(client, app, user)
    bad_hash = _operation(client, headers, delivery, "ack", 1, received_at="2026-08-20T10:00:00Z", package_hash="0" * 64)
    assert bad_hash.status_code == 409
    assert bad_hash.get_json()["error"]["code"] == "package_hash_mismatch"
    ack = _operation(client, headers, delivery, "ack", 1, received_at="2026-08-20T10:00:00Z", package_hash=delivery["package_hash"])
    assert ack.status_code == 200
    started = _operation(client, headers, delivery, "start", 2)
    assert started.status_code == 200
    event_id = str(uuid.uuid4())
    checkpoint = {
        "schema_version": "1.0", "client_event_id": event_id,
        "client_sequence": 1, "event_type": "set_completed",
        "occurred_at": "2026-08-20T12:10:00Z",
        "payload": {"exercise_order": 1, "set_number": 1, "completed_reps": 5},
    }
    first = client.post(f"/api/v1/companion/deliveries/{delivery['id']}/progress", headers={**headers, "Idempotency-Key": "progress-1"}, json=checkpoint)
    assert first.status_code == 201
    duplicate = client.post(f"/api/v1/companion/deliveries/{delivery['id']}/progress", headers={**headers, "Idempotency-Key": "progress-2"}, json=checkpoint)
    assert duplicate.status_code == 200
    assert duplicate.get_json()["data"]["duplicate"] is True
    changed = copy.deepcopy(checkpoint)
    changed["payload"]["completed_reps"] = 4
    conflict = client.post(f"/api/v1/companion/deliveries/{delivery['id']}/progress", headers={**headers, "Idempotency-Key": "progress-3"}, json=changed)
    assert conflict.status_code == 409
    assert conflict.get_json()["error"]["code"] == "progress_event_conflict"
    gap = copy.deepcopy(checkpoint)
    gap["client_event_id"] = str(uuid.uuid4())
    gap["client_sequence"] = 3
    gap_response = client.post(f"/api/v1/companion/deliveries/{delivery['id']}/progress", headers={**headers, "Idempotency-Key": "progress-gap"}, json=gap)
    assert gap_response.status_code == 409
    assert gap_response.get_json()["error"]["details"]["expected_sequence"] == 2
    aborted = _operation(client, headers, delivery, "abort", 3, reason_code="user_cancelled")
    assert aborted.status_code == 200
    after = copy.deepcopy(gap)
    after["client_sequence"] = 2
    assert client.post(f"/api/v1/companion/deliveries/{delivery['id']}/progress", headers={**headers, "Idempotency-Key": "progress-after"}, json=after).status_code == 409


def test_completion_reuses_training_session_is_atomic_idempotent_and_emits_sync(app, client, user):
    headers, planned, delivery = _setup(client, app, user)
    assert _operation(client, headers, delivery, "ack", 1, received_at="2026-08-20T10:00:00Z", package_hash=delivery["package_hash"]).status_code == 200
    assert _operation(client, headers, delivery, "start", 2).status_code == 200
    event_id = str(uuid.uuid4())
    payload = {
        "schema_version": "1.0", "client_event_id": event_id,
        "package_hash": delivery["package_hash"], "base_revision": 3,
        "result": _result(planned["id"], event_id),
    }
    created = client.post(f"/api/v1/companion/deliveries/{delivery['id']}/complete", headers={**headers, "Idempotency-Key": "complete-1"}, json=payload)
    assert created.status_code == 201
    data = created.get_json()["data"]
    assert data["delivery"]["status"] == "completed"
    assert data["delivery"]["training_session_id"] == data["completed_workout"]["id"]
    replay = client.post(f"/api/v1/companion/deliveries/{delivery['id']}/complete", headers={**headers, "Idempotency-Key": "complete-2"}, json=payload)
    assert replay.status_code == 200
    assert replay.get_json()["data"]["completed_workout"]["id"] == data["completed_workout"]["id"]
    with app.app_context():
        assert db.session.execute(db.select(TrainingSession)).scalars().all().__len__() == 1
        assert db.session.execute(db.select(PlannedWorkout)).scalar_one().status == "completed"
        assert db.session.execute(db.select(CompanionWorkoutDelivery)).scalar_one().training_session_id is not None


def test_completion_failure_rolls_back_session_and_delivery(app, client, user, monkeypatch):
    headers, planned, delivery = _setup(client, app, user)
    _operation(client, headers, delivery, "ack", 1, received_at="2026-08-20T10:00:00Z", package_hash=delivery["package_hash"])
    _operation(client, headers, delivery, "start", 2)
    import app.services.companion as companion_service
    original = companion_service.create_completed_workout

    def fail_after_domain_write(**kwargs):
        original(**kwargs)
        raise RuntimeError("synthetic failure after flush")

    monkeypatch.setattr(companion_service, "create_completed_workout", fail_after_domain_write)
    event_id = str(uuid.uuid4())
    payload = {"schema_version": "1.0", "client_event_id": event_id, "package_hash": delivery["package_hash"], "base_revision": 3, "result": _result(planned["id"], event_id)}
    response = client.post(f"/api/v1/companion/deliveries/{delivery['id']}/complete", headers={**headers, "Idempotency-Key": "complete-fail"}, json=payload)
    assert response.status_code == 500
    with app.app_context():
        assert db.session.execute(db.select(TrainingSession)).scalar_one_or_none() is None
        record = db.session.execute(db.select(CompanionWorkoutDelivery)).scalar_one()
        assert record.status == "started"
        assert record.training_session_id is None


def test_cross_user_revoked_device_and_cookie_do_not_access_companion(app, client, user):
    headers, _planned_data, delivery = _setup(client, app, user)
    with app.app_context():
        other = User(username="companion-other", email="companion-other@example.test", role="user")
        other.set_password("other-password")
        db.session.add(other)
        db.session.commit()
    other_tokens = _login(client, "companion-other@example.test", "other-password", "82222222-2222-4222-8222-222222222222")
    other_headers = _auth(other_tokens["access_token"])
    assert client.get(f"/api/v1/companion/deliveries/{delivery['id']}", headers=other_headers).status_code == 404
    assert client.get("/api/v1/companion/profile", headers=other_headers).status_code == 409
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    assert client.get("/api/v1/companion/profile").status_code == 401
    with app.app_context():
        device = db.session.execute(db.select(ApiDevice).where(ApiDevice.public_device_id == DEVICE_ID)).scalar_one()
        device.revoked_at = datetime.now(timezone.utc)
        db.session.commit()
    assert client.post("/api/v1/companion/negotiate", headers=headers, json={}).status_code == 401


def test_sync_bootstrap_reports_honest_companion_capabilities(app, client, user):
    headers, _planned_data, delivery = _setup(client, app, user)
    response = client.get("/api/v1/sync/bootstrap", headers=headers)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["capabilities"]["companion_delivery"] is True
    assert data["capabilities"]["watch_bridge"] is False
    assert data["capabilities"]["continuous_telemetry"] is False
    assert data["companion"]["profile"]["protocol_version"] == "1.0"
    assert data["companion"]["deliveries"][0]["id"] == delivery["id"]


def test_companion_schemas_validate_generated_payloads(app, client, user):
    headers, _planned_data, delivery = _setup(client, app, user)
    payloads = {
        "companion_device_profile": client.get("/api/v1/companion/profile", headers=headers).get_json()["data"],
        "companion_delivery": client.get(f"/api/v1/companion/deliveries/{delivery['id']}", headers=headers).get_json()["data"],
        "companion_workout_package": client.get(f"/api/v1/companion/deliveries/{delivery['id']}/package", headers=headers).get_json()["data"],
    }
    for name, payload in payloads.items():
        schema = json.loads((app.config["SCHEMA_ROOT"] / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


def test_companion_cleanup_is_dry_run_then_expires_only_delivery(app, client, user):
    headers, _planned_data, delivery = _setup(client, app, user)
    with app.app_context():
        record = db.session.execute(db.select(CompanionWorkoutDelivery)).scalar_one()
        record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.session.commit()
    runner = app.test_cli_runner()
    dry = runner.invoke(args=["companion", "cleanup"])
    assert dry.exit_code == 0
    assert "mode=dry-run" in dry.output and "expired_nonterminal=1" in dry.output
    applied = runner.invoke(args=["companion", "cleanup", "--apply"])
    assert applied.exit_code == 0
    with app.app_context():
        assert db.session.execute(db.select(CompanionWorkoutDelivery)).scalar_one().status == "expired"


def test_companion_web_summary_and_prepare_are_owner_only_and_csrf_post(app, client, user):
    plan_id, version_id = _plan(app, user)
    tokens = _login(client)
    headers = _auth(tokens["access_token"])
    assert _negotiate(client, headers).status_code == 201
    planned = _planned(client, headers, plan_id, version_id)
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    listing = client.get("/planned-workouts")
    assert listing.status_code == 200
    assert b"prepare-delivery" in listing.data
    assert b"Preparar para este dispositivo" in listing.data
    prepared = client.post(f"/planned-workouts/{planned['id']}/prepare-delivery", data={"device_id": DEVICE_ID})
    assert prepared.status_code == 302
    devices = client.get("/account/devices")
    assert devices.status_code == 200
    assert b"Companion" in devices.data and b"Entregas recientes" in devices.data
    with app.app_context():
        assert db.session.execute(db.select(CompanionWorkoutDelivery)).scalar_one().status == "prepared"


def test_companion_web_prepare_requires_csrf_when_enabled(app, client, user):
    plan_id, version_id = _plan(app, user)
    tokens = _login(client)
    headers = _auth(tokens["access_token"])
    _negotiate(client, headers)
    planned = _planned(client, headers, plan_id, version_id)
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    app.config["WTF_CSRF_ENABLED"] = True
    denied = client.post(
        f"/planned-workouts/{planned['id']}/prepare-delivery",
        data={"device_id": DEVICE_ID},
    )
    assert denied.status_code == 400


def test_package_limit_completion_hash_and_telemetry_arrays_are_rejected(app, client, user):
    plan_id, version_id = _plan(app, user)
    tokens = _login(client)
    headers = _auth(tokens["access_token"])
    assert _negotiate(client, headers).status_code == 201
    planned = _planned(client, headers, plan_id, version_id)
    app.config["COMPANION_PACKAGE_MAX_BYTES"] = 1024
    renegotiated = _negotiate(client, headers, base_revision=1)
    assert renegotiated.status_code == 200
    too_large = client.post(
        "/api/v1/companion/deliveries",
        headers={**headers, "Idempotency-Key": "too-small-package"},
        json={"schema_version": "1.0", "planned_workout_id": planned["id"]},
    )
    assert too_large.status_code == 413
    assert too_large.get_json()["error"]["code"] == "package_too_large"
    app.config["COMPANION_PACKAGE_MAX_BYTES"] = 262144
    assert _negotiate(client, headers, base_revision=2).status_code == 200
    delivery = _delivery(client, headers, planned["id"], "delivery-after-limit")
    _operation(client, headers, delivery, "ack", 1, received_at="2026-08-20T10:00:00Z", package_hash=delivery["package_hash"])
    _operation(client, headers, delivery, "start", 2)
    event = {
        "schema_version": "1.0", "client_event_id": str(uuid.uuid4()),
        "client_sequence": 1, "event_type": "checkpoint",
        "occurred_at": "2026-08-20T12:00:00Z", "payload": {"message_code": ["not", "telemetry"]},
    }
    rejected = client.post(
        f"/api/v1/companion/deliveries/{delivery['id']}/progress",
        headers={**headers, "Idempotency-Key": "array-telemetry"}, json=event,
    )
    assert rejected.status_code == 400
    result_id = str(uuid.uuid4())
    bad_completion = {
        "schema_version": "1.0", "client_event_id": result_id,
        "package_hash": "0" * 64, "base_revision": 3,
        "result": _result(planned["id"], result_id),
    }
    mismatch = client.post(
        f"/api/v1/companion/deliveries/{delivery['id']}/complete",
        headers={**headers, "Idempotency-Key": "completion-bad-hash"}, json=bad_completion,
    )
    assert mismatch.status_code == 409
    assert mismatch.get_json()["error"]["code"] == "package_hash_mismatch"


@pytest.mark.skipif(
    not Path("/.dockerenv").exists(),
    reason="MariaDB companion concurrency contract runs only in Docker",
)
def test_mariadb_concurrent_delivery_and_progress_are_single_winner(app, tmp_path):
    username = f"companion-race-{uuid.uuid4().hex}"
    concurrent_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "companion-race-web-secret-key-long-enough",
        "API_TOKEN_SIGNING_KEY": "companion-race-api-key-long-enough",
        "DATA_ROOT": tmp_path / "companion-race",
        "UPLOAD_ROOT": tmp_path / "companion-race" / "raw",
        "GENERATED_UPLOAD_ROOT": tmp_path / "companion-race" / "generated",
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC", "WTF_CSRF_ENABLED": False,
        "API_RATE_LIMIT_ENABLED": False,
    })
    with concurrent_app.app_context():
        account = User(username=username, email=f"{username}@example.test", role="user")
        account.set_password("race-test-password")
        db.session.add(account)
        db.session.commit()
        user_id = account.id
    try:
        plan_id, version_id = _plan(concurrent_app, user_id)
        login = _login(concurrent_app.test_client(), f"{username}@example.test", "race-test-password", "83333333-3333-4333-8333-333333333333")
        headers = _auth(login["access_token"])
        _negotiate(concurrent_app.test_client(), headers)
        planned = _planned(concurrent_app.test_client(), headers, plan_id, version_id)
        barrier = Barrier(2)

        def prepare(index):
            with concurrent_app.test_client() as race_client:
                barrier.wait(timeout=10)
                response = race_client.post(
                    "/api/v1/companion/deliveries",
                    headers={**headers, "Idempotency-Key": f"delivery-race-{index}"},
                    json={"schema_version": "1.0", "planned_workout_id": planned["id"]},
                )
                return response.status_code, response.get_json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(prepare, range(2)))
        assert sorted(code for code, _body in results) == [200, 201]
        delivery_ids = {body["data"]["id"] for _code, body in results}
        assert len(delivery_ids) == 1
        delivery_id = delivery_ids.pop()
        delivery = results[0][1]["data"]
        _operation(concurrent_app.test_client(), headers, delivery, "ack", 1, received_at="2026-08-20T10:00:00Z", package_hash=delivery["package_hash"])
        _operation(concurrent_app.test_client(), headers, delivery, "start", 2)
        event_id = str(uuid.uuid4())
        event = {"schema_version": "1.0", "client_event_id": event_id, "client_sequence": 1, "event_type": "heartbeat", "occurred_at": "2026-08-20T12:00:00Z", "payload": {"elapsed_seconds": 10}}
        event_barrier = Barrier(2)

        def progress(index):
            with concurrent_app.test_client() as race_client:
                event_barrier.wait(timeout=10)
                return race_client.post(
                    f"/api/v1/companion/deliveries/{delivery_id}/progress",
                    headers={**headers, "Idempotency-Key": f"progress-race-{index}"}, json=event,
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            progress_codes = list(pool.map(progress, range(2)))
        assert sorted(progress_codes) == [200, 201]
        with concurrent_app.app_context():
            assert db.session.execute(db.select(db.func.count(CompanionWorkoutDelivery.id)).where(CompanionWorkoutDelivery.user_id == user_id)).scalar_one() == 1
            assert db.session.execute(db.select(db.func.count(CompanionProgressEvent.id)).where(CompanionProgressEvent.user_id == user_id)).scalar_one() == 1
    finally:
        with concurrent_app.app_context():
            account = db.session.get(User, user_id)
            if account is not None:
                db.session.delete(account)
                db.session.commit()


def test_companion_profile_cascade_migration_is_reversible_on_sqlite(tmp_path):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260714_0025_companion_profile_cascade.py"
    )
    spec = importlib.util.spec_from_file_location(
        "companion_profile_cascade_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'companion-migration.db'}")
    metadata = sa.MetaData()
    sa.Table(
        "companion_device_profiles",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    sa.Table(
        "companion_workout_deliveries",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("companion_device_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    metadata.create_all(engine)

    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
        upgraded_fk = sa.inspect(engine).get_foreign_keys(
            "companion_workout_deliveries"
        )[0]
        assert upgraded_fk["name"] == "fk_companion_deliveries_profile"
        assert upgraded_fk["options"]["ondelete"] == "CASCADE"

        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.downgrade()
        downgraded_fk = sa.inspect(engine).get_foreign_keys(
            "companion_workout_deliveries"
        )[0]
        assert (
            downgraded_fk["name"]
            == "fk_companion_deliveries_profile_restrict"
        )
        assert downgraded_fk["options"]["ondelete"] == "RESTRICT"
    finally:
        engine.dispose()
