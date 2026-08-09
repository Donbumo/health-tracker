from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import (
    ApiDevice,
    ApiRefreshToken,
    ApiSession,
    CompanionDeviceProfile,
    CompanionProgressEvent,
    CompanionWorkoutDelivery,
    DeviceSyncState,
    IdempotencyRecord,
    PlannedWorkout,
    SyncChange,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    User,
)
from app.services.api_device_deletion import ApiDeviceDeletionService
from tests.conftest import login


DEVICE_ID = "91111111-1111-4111-8111-111111111111"
OTHER_DEVICE_ID = "92222222-2222-4222-8222-222222222222"


def _device(user_id: int, *, public_id: str = DEVICE_ID, revoked: bool = True):
    return ApiDevice(
        user_id=user_id,
        public_device_id=public_id,
        name="Android QA ficticio",
        platform="android",
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )


def _technical_graph(user_id: int, *, delivery_status: str = "completed") -> dict:
    now = datetime.now(timezone.utc)
    device = _device(user_id)
    plan = TrainingPlan(
        user_id=user_id,
        name="Plan QA preservado",
        active_version_number=1,
    )
    db.session.add_all([device, plan])
    db.session.flush()
    version = TrainingPlanVersion(
        user_id=user_id,
        training_plan_id=plan.id,
        version_number=1,
        schema_version="1.0",
        sha256="a" * 64,
        content={"qa": "fixture-ficticia"},
    )
    db.session.add(version)
    db.session.flush()
    planned = PlannedWorkout(
        user_id=user_id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        scheduled_for_date=date(2026, 9, 1),
        timezone="UTC",
        status="completed",
        title_snapshot="Entrenamiento QA preservado",
        payload_snapshot_json={"qa": "fixture-ficticia"},
        source_version=1,
        revision=1,
        last_modified_by_device_id=device.id,
    )
    api_session = ApiSession(
        user_id=user_id,
        device_id=device.id,
        public_session_id="93333333-3333-4333-8333-333333333333",
        token_family_id="94444444-4444-4444-8444-444444444444",
        expires_at=now + timedelta(days=30),
        revoked_at=now,
        revoke_reason="qa_revoked",
    )
    profile = CompanionDeviceProfile(
        user_id=user_id,
        api_device_id=device.id,
        supported_metrics_json=["reps"],
        supported_features_json=["offline"],
    )
    db.session.add_all([planned, api_session, profile])
    db.session.flush()
    refresh = ApiRefreshToken(
        session_id=api_session.id,
        public_token_id="95555555-5555-4555-8555-555555555555",
        token_hash="b" * 64,
        expires_at=now + timedelta(days=30),
        revoked_at=now,
    )
    training = TrainingSession(
        user_id=user_id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        planned_workout_id=planned.id,
        source_device_id=device.id,
        client_event_id="96666666-6666-4666-8666-666666666666",
        performed_at=now,
        started_at=now - timedelta(minutes=30),
        completed_at=now,
        timezone="UTC",
        planned_week_number=1,
        planned_day_number=1,
        duration_seconds=1800,
    )
    db.session.add_all([refresh, training])
    db.session.flush()
    exercise = TrainingSessionExercise(
        user_id=user_id,
        training_session_id=training.id,
        exercise_order=1,
        planned_exercise_order=1,
        name="Sentadilla QA preservada",
    )
    delivery = CompanionWorkoutDelivery(
        user_id=user_id,
        api_device_id=device.id,
        profile_id=profile.id,
        planned_workout_id=planned.id,
        planned_workout_revision=planned.revision,
        package_schema_version="1.0",
        package_hash="c" * 64,
        payload_snapshot_json={"qa": "fixture-ficticia"},
        status=delivery_status,
        revision=1,
        training_session_id=training.id if delivery_status == "completed" else None,
    )
    sync_state = DeviceSyncState(
        user_id=user_id,
        device_id=device.id,
        last_pull_sequence=0,
    )
    idempotency = IdempotencyRecord(
        user_id=user_id,
        device_id=device.id,
        key_hash="d" * 64,
        operation="qa_delete_fixture",
        request_hash="e" * 64,
        expires_at=now + timedelta(days=1),
    )
    sync_change = SyncChange(
        user_id=user_id,
        entity_type="completed_workout",
        entity_public_id=training.public_id,
        operation="upsert",
        revision=1,
        changed_by_device_id=device.id,
        payload_hash="f" * 64,
        payload_json={"qa": "fixture-ficticia"},
    )
    db.session.add_all(
        [exercise, delivery, sync_state, idempotency, sync_change]
    )
    db.session.flush()
    training_set = TrainingSet(
        user_id=user_id,
        training_session_exercise_id=exercise.id,
        set_number=1,
        planned_set_number=1,
        weight_kg=Decimal("40.00"),
        reps=5,
    )
    progress = CompanionProgressEvent(
        user_id=user_id,
        delivery_id=delivery.id,
        api_device_id=device.id,
        client_event_id="97777777-7777-4777-8777-777777777777",
        client_sequence=1,
        event_type="checkpoint",
        occurred_at=now,
        payload_json={"qa": "fixture-ficticia"},
        payload_hash="1" * 64,
    )
    db.session.add_all([training_set, progress])
    db.session.commit()
    return {
        "device": device.id,
        "profile": profile.id,
        "delivery": delivery.id,
        "progress": progress.id,
        "api_session": api_session.id,
        "refresh": refresh.id,
        "sync_state": sync_state.id,
        "idempotency": idempotency.id,
        "training": training.id,
        "exercise": exercise.id,
        "training_set": training_set.id,
        "planned": planned.id,
        "sync_change": sync_change.sequence,
    }


def _delete(client, device_id: str = DEVICE_ID, **kwargs):
    data = kwargs.pop("data", {"confirm_delete": "yes"})
    return client.post(
        f"/account/devices/{device_id}/delete",
        data=data,
        **kwargs,
    )


def test_owner_deletes_eligible_device_and_only_technical_dependencies(
    app, client, user
):
    with app.app_context():
        ids = _technical_graph(user)

    login(client)
    page_before = client.get("/account/devices").get_data(as_text=True)
    assert "Eliminar dispositivo permanentemente" in page_before
    response = _delete(client, follow_redirects=True)
    assert response.status_code == 200
    assert "Dispositivo eliminado permanentemente" in response.get_data(as_text=True)
    assert "Android QA ficticio" not in client.get("/account/devices").get_data(as_text=True)

    with app.app_context():
        for model, key in (
            (ApiDevice, "device"),
            (ApiSession, "api_session"),
            (ApiRefreshToken, "refresh"),
            (CompanionDeviceProfile, "profile"),
            (CompanionWorkoutDelivery, "delivery"),
            (CompanionProgressEvent, "progress"),
            (DeviceSyncState, "sync_state"),
            (IdempotencyRecord, "idempotency"),
        ):
            assert db.session.get(model, ids[key]) is None

        training = db.session.get(TrainingSession, ids["training"])
        planned = db.session.get(PlannedWorkout, ids["planned"])
        sync_change = db.session.get(SyncChange, ids["sync_change"])
        assert training is not None and training.source_device_id is None
        assert db.session.get(TrainingSessionExercise, ids["exercise"]) is not None
        assert db.session.get(TrainingSet, ids["training_set"]) is not None
        assert planned is not None and planned.last_modified_by_device_id is None
        assert sync_change is not None and sync_change.changed_by_device_id is None


def test_active_device_is_rejected_without_database_changes(app, client, user):
    with app.app_context():
        device = _device(user, revoked=False)
        db.session.add(device)
        db.session.commit()
        device_pk = device.id

    login(client)
    page = client.get("/account/devices").get_data(as_text=True)
    assert "Revocar dispositivo" in page
    assert "Eliminar dispositivo permanentemente" not in page
    response = _delete(client, follow_redirects=True)
    assert "Revoca el dispositivo" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ApiDevice, device_pk) is not None


def test_revoked_device_with_active_api_session_is_rejected(app, client, user):
    with app.app_context():
        device = _device(user)
        db.session.add(device)
        db.session.flush()
        api_session = ApiSession(
            user_id=user,
            device_id=device.id,
            public_session_id="98888888-8888-4888-8888-888888888888",
            token_family_id="99999999-9999-4999-8999-999999999999",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.session.add(api_session)
        db.session.commit()
        device_pk = device.id

    login(client)
    response = _delete(client, follow_redirects=True)
    assert "sesión API activa" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ApiDevice, device_pk) is not None


def test_device_with_pending_companion_delivery_is_rejected(app, client, user):
    with app.app_context():
        ids = _technical_graph(user, delivery_status="prepared")

    login(client)
    page = client.get("/account/devices").get_data(as_text=True)
    assert "Eliminar dispositivo permanentemente" not in page
    response = _delete(client, follow_redirects=True)
    assert "entrega Companion pendiente o activa" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ApiDevice, ids["device"]) is not None
        assert db.session.get(CompanionWorkoutDelivery, ids["delivery"]) is not None


def test_other_users_device_is_not_disclosed_or_deleted(app, client, user):
    with app.app_context():
        other = User(username="qa-device-owner", role="user")
        other.set_password("fictitious-password")
        db.session.add(other)
        db.session.flush()
        device = _device(other.id, public_id=OTHER_DEVICE_ID)
        db.session.add(device)
        db.session.commit()
        device_pk = device.id

    login(client)
    assert _delete(client, OTHER_DEVICE_ID).status_code == 404
    with app.app_context():
        assert db.session.get(ApiDevice, device_pk) is not None


def test_delete_requires_explicit_confirmation(app, client, user):
    with app.app_context():
        device = _device(user)
        db.session.add(device)
        db.session.commit()
        device_pk = device.id

    login(client)
    response = _delete(client, data={}, follow_redirects=True)
    assert "Confirma explícitamente" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ApiDevice, device_pk) is not None


def test_delete_rejects_invalid_csrf(app, client, user):
    with app.app_context():
        device = _device(user)
        db.session.add(device)
        db.session.commit()
        device_pk = device.id

    login(client)
    app.config["WTF_CSRF_ENABLED"] = True
    response = _delete(
        client,
        data={"confirm_delete": "yes", "csrf_token": "invalid-qa-token"},
    )
    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(ApiDevice, device_pk) is not None


def test_intermediate_failure_rolls_back_all_device_deletion_changes(
    app, client, user, monkeypatch
):
    with app.app_context():
        ids = _technical_graph(user)

    def fail_after_first_delete(_service, device):
        db.session.execute(
            db.delete(DeviceSyncState).where(DeviceSyncState.device_id == device.id)
        )
        db.session.flush()
        raise SQLAlchemyError("qa_intermediate_failure")

    monkeypatch.setattr(
        ApiDeviceDeletionService,
        "_delete_technical_records",
        fail_after_first_delete,
    )
    login(client)
    response = _delete(client, follow_redirects=True)
    assert "no se aplicaron cambios parciales" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ApiDevice, ids["device"]) is not None
        assert db.session.get(DeviceSyncState, ids["sync_state"]) is not None
        assert db.session.get(ApiSession, ids["api_session"]) is not None
