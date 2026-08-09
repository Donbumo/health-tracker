import importlib.util
import copy
from pathlib import Path
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator, FormatChecker
import sqlalchemy as sa
from sqlalchemy import event

from app.extensions import db
from app.models import (
    ApiDevice,
    CompanionDeviceProfile,
    Exercise,
    ExerciseAlias,
    PlannedWorkout,
    TrainingPlan,
    TrainingPlanWorkout,
    User,
)
from app.services.companion import prepare_delivery
from app.services.mobile_planning import list_plans
from app.services.mobile_sync import PlannedWorkoutService, serialize_planned_workout
from tests.test_mobile_sync import _api_login, _auth


def _headers(token: str, key: str | None = None) -> dict:
    values = _auth(token)
    if key:
        values["Idempotency-Key"] = key
    return values


def _create_plan(client, token, *, public_id=None, key="plan-create"):
    payload = {
        "public_id": public_id or str(uuid.uuid4()),
        "name": "Rutina Alpha 1.3 ficticia",
        "description": "Solo datos QA.",
    }
    return client.post("/api/v1/mobile/plans", json=payload, headers=_headers(token, key))


def _prescriptions():
    return [
        {
            "id": str(uuid.uuid4()),
            "name": "Sentadilla QA",
            "notes": "Prescripción ficticia",
            "sets": [
                {
                    "id": str(uuid.uuid4()),
                    "reps_min": 6,
                    "reps_max": 8,
                    "weight_kg": "40",
                    "load_value": "20",
                    "load_unit": "kg",
                    "load_mode": "per_side",
                    "rir": "2",
                    "rpe": "8",
                    "rest_seconds": 120,
                }
            ],
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Carrera QA",
            "sets": [
                {
                    "id": str(uuid.uuid4()),
                    "load_mode": "duration_distance",
                    "load_unit": "kg",
                    "duration_seconds": 600,
                    "distance_m": "1500",
                }
            ],
        },
    ]


def _planning_validator(app):
    schema = Path(app.config["SCHEMA_ROOT"], "mobile_planning.schema.json")
    return Draft202012Validator(
        __import__("json").loads(schema.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


def test_catalog_search_pagination_and_schema(app, client, user):
    with app.app_context():
        for name in ("Press QA", "Prensa QA", "Remo QA"):
            exercise = Exercise(
                user_id=user,
                canonical_name=name,
                normalized_name=name.casefold(),
            )
            db.session.add(exercise)
            if name == "Remo QA":
                exercise.aliases.append(ExerciseAlias(user_id=user, alias_name="Jalón QA", normalized_name="jalón qa"))
        db.session.commit()
    token = _api_login(client)["access_token"]

    first = client.get(
        "/api/v1/mobile/exercises?search=pre&limit=1", headers=_headers(token)
    )
    assert first.status_code == 200
    body = first.get_json()["data"]
    assert len(body["items"]) == 1
    assert body["has_more"] is True
    assert body["available_filters"] == {"equipment": False, "muscle_group": False}
    second = client.get(
        f"/api/v1/mobile/exercises?search=pre&limit=1&cursor={body['next_cursor']}",
        headers=_headers(token),
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["items"][0]["public_id"] != body["items"][0]["public_id"]
    assert client.get(
        "/api/v1/mobile/exercises?equipment=barra", headers=_headers(token)
    ).status_code == 400
    alias_match = client.get(
        "/api/v1/mobile/exercises?search=jalón", headers=_headers(token)
    )
    assert alias_match.status_code == 200
    assert alias_match.get_json()["data"]["items"][0]["name"] == "Remo QA"

    assert not list(_planning_validator(app).iter_errors(body))


def test_plan_workout_versioning_duplicate_conflict_and_rollback(app, client, user):
    token = _api_login(client)["access_token"]
    created = _create_plan(client, token)
    assert created.status_code == 201
    assert not list(_planning_validator(app).iter_errors(created.get_json()["data"]))
    plan_id = created.get_json()["data"]["public_id"]
    replay = _create_plan(
        client,
        token,
        public_id=plan_id,
    )
    assert replay.status_code == 201
    assert replay.get_json()["data"]["public_id"] == plan_id
    mismatched_replay = client.post(
        "/api/v1/mobile/plans",
        headers=_headers(token, "plan-create"),
        json={"public_id": plan_id, "name": "Payload distinto QA"},
    )
    assert mismatched_replay.status_code == 409

    workout_id = str(uuid.uuid4())
    workout = client.post(
        f"/api/v1/mobile/plans/{plan_id}/workouts",
        headers=_headers(token, "workout-create"),
        json={
            "public_id": workout_id,
            "base_revision": 1,
            "name": "Fuerza QA",
            "notes": "Entrenamiento ficticio",
            "exercises": _prescriptions(),
        },
    )
    assert workout.status_code == 201
    assert not list(_planning_validator(app).iter_errors(workout.get_json()["data"]))
    detail = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=_headers(token))
    assert detail.status_code == 200
    plan = detail.get_json()["data"]
    assert not list(_planning_validator(app).iter_errors(plan))
    assert plan["revision"] == 2
    assert plan["active_version"] == 1
    assert plan["workouts"][0]["exercises"][0]["sets"][0]["load_mode"] == "per_side"

    edited = client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(token, "workout-edit"),
        json={"base_revision": 1, "name": "Fuerza QA editada"},
    )
    assert edited.status_code == 200
    stale = client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(token, "workout-stale"),
        json={"base_revision": 1, "name": "No debe persistir"},
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"]["details"]["resolution_options"] == [
        "keep_remote",
        "retry_local_copy",
    ]
    invalid = client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(token, "workout-invalid"),
        json={
            "base_revision": 2,
            "exercises": [{"name": "Inválido", "sets": []}],
        },
    )
    assert invalid.status_code == 400
    with app.app_context():
        record = db.session.execute(
            db.select(TrainingPlanWorkout).where(TrainingPlanWorkout.public_id == workout_id)
        ).scalar_one()
        assert record.revision == 2
        assert record.name == "Fuerza QA editada"

    prescribed = plan["workouts"][0]["exercises"]
    reordered_prescriptions = client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(token, "exercise-reorder"),
        json={"base_revision": 2, "exercises": [prescribed[1], prescribed[0]]},
    )
    assert reordered_prescriptions.status_code == 200
    detail = client.get(f"/api/v1/mobile/workouts/{workout_id}", headers=_headers(token)).get_json()["data"]
    assert [item["name"] for item in detail["exercises"]] == ["Carrera QA", "Sentadilla QA"]

    duplicated_prescription = copy.deepcopy(detail["exercises"][1])
    duplicated_prescription["id"] = str(uuid.uuid4())
    duplicated_prescription["sets"][0]["id"] = str(uuid.uuid4())
    duplicated_prescription["name"] = "Sentadilla QA duplicada"
    duplicated_prescriptions = client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(token, "exercise-duplicate"),
        json={"base_revision": 3, "exercises": detail["exercises"] + [duplicated_prescription]},
    )
    assert duplicated_prescriptions.status_code == 200
    detail = client.get(f"/api/v1/mobile/workouts/{workout_id}", headers=_headers(token)).get_json()["data"]
    assert len(detail["exercises"]) == 3
    assert len({item["id"] for item in detail["exercises"]}) == 3

    removed_prescription = client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(token, "exercise-remove"),
        json={"base_revision": 4, "exercises": detail["exercises"][1:]},
    )
    assert removed_prescription.status_code == 200
    detail = client.get(f"/api/v1/mobile/workouts/{workout_id}", headers=_headers(token)).get_json()["data"]
    assert [item["exercise_order"] for item in detail["exercises"]] == [1, 2]
    assert "Carrera QA" not in {item["name"] for item in detail["exercises"]}

    copied = client.post(
        f"/api/v1/mobile/plans/{plan_id}/duplicate",
        headers=_headers(token, "plan-copy"),
        json={"name": "Rutina copia QA"},
    )
    assert copied.status_code == 201
    copied_detail = client.get(
        f"/api/v1/mobile/plans/{copied.get_json()['data']['public_id']}",
        headers=_headers(token),
    ).get_json()["data"]
    assert copied_detail["workout_count"] == 1
    assert copied_detail["workouts"][0]["public_id"] != workout_id

    second_id = str(uuid.uuid4())
    second = client.post(
        f"/api/v1/mobile/plans/{plan_id}/workouts",
        headers=_headers(token, "second-workout"),
        json={"public_id": second_id, "base_revision": 6, "name": "Segundo QA", "exercises": _prescriptions()},
    )
    assert second.status_code == 201
    reordered = client.patch(
        f"/api/v1/mobile/plans/{plan_id}",
        headers=_headers(token, "plan-reorder"),
        json={"base_revision": 7, "workout_order": [second_id, workout_id]},
    )
    assert reordered.status_code == 200
    reordered_detail = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=_headers(token))
    assert [item["public_id"] for item in reordered_detail.get_json()["data"]["workouts"]] == [second_id, workout_id]
    duplicated_workout = client.post(
        f"/api/v1/mobile/workouts/{workout_id}/duplicate",
        headers=_headers(token, "workout-copy"),
        json={"base_revision": 8},
    )
    assert duplicated_workout.status_code == 201
    archived = client.patch(
        f"/api/v1/mobile/plans/{plan_id}",
        headers=_headers(token, "plan-archive"),
        json={"base_revision": 9, "status": "archived"},
    )
    assert archived.status_code == 200
    assert archived.get_json()["data"]["status"] == "archived"
    assert _create_plan(client, token, key="oversized-plan", public_id=str(uuid.uuid4())).status_code == 201
    assert client.post(
        "/api/v1/mobile/plans",
        headers=_headers(token, "invalid-size"),
        json={"name": "x" * 201},
    ).status_code == 400
    limited_plan = _create_plan(client, token, key="exercise-limit-plan")
    limited_plan_id = limited_plan.get_json()["data"]["public_id"]
    too_many_exercises = [
        {
            "id": str(uuid.uuid4()),
            "name": f"Ejercicio límite QA {index}",
            "sets": [{"id": str(uuid.uuid4()), "reps": 1}],
        }
        for index in range(101)
    ]
    assert client.post(
        f"/api/v1/mobile/plans/{limited_plan_id}/workouts",
        headers=_headers(token, "exercise-limit"),
        json={"public_id": str(uuid.uuid4()), "base_revision": 1, "name": "Límite QA", "exercises": too_many_exercises},
    ).status_code == 400
    unchanged = client.get(f"/api/v1/mobile/plans/{limited_plan_id}", headers=_headers(token)).get_json()["data"]
    assert unchanged["revision"] == 1
    assert unchanged["workout_count"] == 0


def test_plan_list_query_count_is_bounded(app, client, user):
    token = _api_login(client)["access_token"]
    for index in range(5):
        assert _create_plan(
            client,
            token,
            public_id=str(uuid.uuid4()),
            key=f"query-budget-{index}",
        ).status_code == 201

    with app.app_context():
        statements = []

        def count_query(*_args):
            statements.append(1)

        event.listen(db.engine, "before_cursor_execute", count_query)
        try:
            plans = list_plans(user)
        finally:
            event.remove(db.engine, "before_cursor_execute", count_query)
        assert len(plans) == 5
        assert len(statements) <= 3
        assert not list(_planning_validator(app).iter_errors({"items": plans}))


def test_schedule_timezone_delivery_cancel_ownership_and_no_duplicates(app, client, user):
    token = _api_login(client)["access_token"]
    plan_id = _create_plan(client, token).get_json()["data"]["public_id"]
    workout_id = str(uuid.uuid4())
    assert client.post(
        f"/api/v1/mobile/plans/{plan_id}/workouts",
        headers=_headers(token, "schedule-workout"),
        json={
            "public_id": workout_id,
            "base_revision": 1,
            "name": "Calendario QA",
            "exercises": _prescriptions(),
        },
    ).status_code == 201
    scheduled_id = str(uuid.uuid4())
    schedule_payload = {
        "public_id": scheduled_id,
        "scheduled_for_date": "2026-07-25",
        "timezone": "America/Mexico_City",
    }
    scheduled = client.post(
        f"/api/v1/mobile/workouts/{workout_id}/schedule",
        headers=_headers(token, "schedule-create"),
        json=schedule_payload,
    )
    assert scheduled.status_code == 201
    replay = client.post(
        f"/api/v1/mobile/workouts/{workout_id}/schedule",
        headers=_headers(token, "schedule-create"),
        json=schedule_payload,
    )
    assert replay.status_code == 201
    with app.app_context():
        assert db.session.execute(
            db.select(db.func.count(PlannedWorkout.id)).where(
                PlannedWorkout.public_id == scheduled_id
            )
        ).scalar_one() == 1
        device = db.session.execute(
            db.select(ApiDevice).where(ApiDevice.user_id == user)
        ).scalar_one()
        profile = CompanionDeviceProfile(
            user_id=user,
            api_device_id=device.id,
            protocol_version="1.0",
            workout_schema_version="1.0",
            result_schema_version="1.0",
            supported_features_json=["offline", "rest_timer", "weight", "rir", "rpe"],
            supported_metrics_json=["reps", "weight_kg", "rir", "rpe", "rest_seconds"],
            supports_offline=True,
            supports_rest_timer=True,
            supports_weight=True,
            supports_rir=True,
            supports_rpe=True,
        )
        db.session.add(profile)
        db.session.flush()
        delivery, duplicate = prepare_delivery(
            user_id=user, device=device, planned_public_id=scheduled_id
        )
        assert duplicate is False
        assert delivery.payload_snapshot_json["scheduled_for_date"] == "2026-07-25"
        assert delivery.payload_snapshot_json["exercises"][0]["sets"][0]["load_mode"] == "per_side"
        db.session.rollback()

        other = User(username="other-planning-user", role="user")
        other.set_password("other-password")
        db.session.add(other)
        db.session.commit()
    other_token = _api_login(
        client,
        username="other-planning-user",
        password="other-password",
        device_id="72222222-2222-4222-8222-222222222222",
    )["access_token"]
    assert client.get(f"/api/v1/mobile/plans/{plan_id}", headers=_headers(other_token)).status_code == 404
    assert client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(other_token, "foreign-edit"),
        json={"base_revision": 1, "name": "Ajeno"},
    ).status_code == 404
    assert client.get(
        f"/api/v1/planned-workouts/{scheduled_id}",
        headers=_headers(other_token),
    ).status_code == 404
    assert client.patch(
        f"/api/v1/planned-workouts/{scheduled_id}",
        headers=_headers(other_token, "foreign-schedule-move"),
        json={"base_revision": 1, "scheduled_for_date": "2026-07-26", "timezone": "UTC"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/mobile/scheduled-workouts/{scheduled_id}",
        headers=_headers(other_token, "foreign-schedule-delete"),
        json={"base_revision": 1},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/mobile/scheduled-workouts/{scheduled_id}",
        headers=_headers(token, "schedule-delete"),
        json={"base_revision": 1},
    ).status_code == 200
    moved_id = str(uuid.uuid4())
    moved = client.post(
        f"/api/v1/mobile/workouts/{workout_id}/schedule",
        headers=_headers(token, "schedule-rescheduled"),
        json={**schedule_payload, "public_id": moved_id, "scheduled_for_date": "2026-07-27"},
    )
    assert moved.status_code == 201
    assert moved.get_json()["data"]["scheduled_for_date"] == "2026-07-27"
    with app.app_context():
        records = db.session.execute(
            db.select(PlannedWorkout).where(PlannedWorkout.public_id.in_([scheduled_id, moved_id]))
        ).scalars().all()
        assert len(records) == 2
        assert sum(record.deleted_at is None for record in records) == 1


def test_agenda_reschedule_archive_safety_and_package_revision(app, client, user):
    with app.app_context():
        owner = User(username="agenda-owner-qa", role="user")
        owner.set_password("agenda-owner-password")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id
    token = _api_login(
        client,
        username="agenda-owner-qa",
        password="agenda-owner-password",
        device_id="73333333-3333-4333-8333-333333333333",
    )["access_token"]
    plan_id = _create_plan(client, token, key="agenda-plan").get_json()["data"]["public_id"]
    workout_id = str(uuid.uuid4())
    created_workout = client.post(
        f"/api/v1/mobile/plans/{plan_id}/workouts",
        headers=_headers(token, "agenda-workout"),
        json={
            "public_id": workout_id,
            "base_revision": 1,
            "name": "Agenda QA",
            "exercises": _prescriptions(),
        },
    )
    assert created_workout.status_code == 201
    empty_agenda = client.get(
        "/api/v1/planned-workouts?from=2028-01-01&to=2028-01-07",
        headers=_headers(token),
    )
    assert empty_agenda.status_code == 200
    assert empty_agenda.get_json()["data"] == []
    schedule_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for index, scheduled_id in enumerate(schedule_ids):
        response = client.post(
            f"/api/v1/mobile/workouts/{workout_id}/schedule",
            headers=_headers(token, f"agenda-schedule-{index}"),
            json={
                "public_id": scheduled_id,
                "scheduled_for_date": "2028-02-29",
                "timezone": "America/Mexico_City",
            },
        )
        assert response.status_code == 201

    agenda = client.get(
        "/api/v1/planned-workouts?from=2028-02-01&to=2028-02-29",
        headers=_headers(token),
    )
    assert agenda.status_code == 200
    assert [item["id"] for item in agenda.get_json()["data"]] == sorted(schedule_ids)
    assert all(item["timezone"] == "America/Mexico_City" for item in agenda.get_json()["data"])
    week = client.get(
        "/api/v1/planned-workouts?from=2028-02-28&to=2028-03-05",
        headers=_headers(token),
    )
    assert len(week.get_json()["data"]) == 2
    assert client.get(
        "/api/v1/planned-workouts?from=2028-01-01&to=2029-02-01",
        headers=_headers(token),
    ).status_code == 400

    moved = client.patch(
        f"/api/v1/planned-workouts/{schedule_ids[0]}",
        headers=_headers(token, "agenda-move"),
        json={"base_revision": 1, "scheduled_for_date": "2028-03-01", "timezone": "America/Mexico_City"},
    )
    assert moved.status_code == 200
    assert moved.get_json()["data"]["id"] == schedule_ids[0]
    assert moved.get_json()["data"]["revision"] == 2
    stale = client.patch(
        f"/api/v1/planned-workouts/{schedule_ids[0]}",
        headers=_headers(token, "agenda-move-stale"),
        json={"base_revision": 1, "scheduled_for_date": "2028-03-02", "timezone": "UTC"},
    )
    assert stale.status_code == 409

    blocked = client.patch(
        f"/api/v1/mobile/plans/{plan_id}",
        headers=_headers(token, "agenda-archive-blocked"),
        json={"base_revision": 2, "status": "archived"},
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["error"]["code"] == "active_schedules"
    assert blocked.get_json()["error"]["details"]["active_schedule_count"] == 2
    after_block = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=_headers(token)).get_json()["data"]
    assert after_block["status"] == "active"
    assert after_block["revision"] == 2

    with app.app_context():
        device = db.session.execute(db.select(ApiDevice).where(ApiDevice.user_id == owner_id)).scalar_one()
        profile = CompanionDeviceProfile(
            user_id=owner_id,
            api_device_id=device.id,
            protocol_version="1.0",
            workout_schema_version="1.0",
            result_schema_version="1.0",
            supported_features_json=["offline", "rest_timer", "weight", "rir", "rpe"],
            supported_metrics_json=["reps", "weight_kg", "rir", "rpe", "rest_seconds"],
            supports_offline=True,
            supports_rest_timer=True,
            supports_weight=True,
            supports_rir=True,
            supports_rpe=True,
        )
        db.session.add(profile)
        db.session.commit()
        first_delivery, duplicate = prepare_delivery(
            user_id=owner_id,
            device=device,
            planned_public_id=schedule_ids[0],
        )
        first_hash = first_delivery.package_hash
        first_delivery_id = first_delivery.public_id
        first_snapshot = copy.deepcopy(first_delivery.payload_snapshot_json)
        assert [item["name"] for item in first_snapshot["exercises"]] == ["Sentadilla QA", "Carrera QA"]
        assert first_snapshot["exercises"][0]["sets"][0]["load_mode"] == "per_side"
        assert first_snapshot["exercises"][1]["sets"][0]["load_mode"] == "duration_distance"
        assert first_snapshot["exercises"][1]["sets"][0]["duration_seconds"] == 600
        assert first_snapshot["exercises"][1]["sets"][0]["distance_m"] == "1500"
        db.session.commit()
        assert duplicate is False

    updated = client.patch(
        f"/api/v1/mobile/workouts/{workout_id}",
        headers=_headers(token, "agenda-workout-update"),
        json={
            "base_revision": 1,
            "name": "Agenda QA actualizada",
            "exercises": _prescriptions(),
        },
    )
    assert updated.status_code == 200

    with app.app_context():
        device = db.session.execute(db.select(ApiDevice).where(ApiDevice.user_id == owner_id)).scalar_one()
        planned = PlannedWorkoutService.get_by_public_id(owner_id, schedule_ids[0])
        assert planned.revision == 3
        second_delivery, duplicate = prepare_delivery(
            user_id=owner_id,
            device=device,
            planned_public_id=schedule_ids[0],
        )
        assert duplicate is False
        assert second_delivery.public_id != first_delivery_id
        assert second_delivery.package_hash != first_hash
        assert first_snapshot["title"] == "Agenda QA"
        assert planned.payload_snapshot_json["day"]["name"] == "Agenda QA actualizada"
        replay, replay_duplicate = prepare_delivery(
            user_id=owner_id,
            device=device,
            planned_public_id=schedule_ids[0],
        )
        assert replay_duplicate is True
        assert replay.public_id == second_delivery.public_id
        assert replay.payload_snapshot_json == second_delivery.payload_snapshot_json
        db.session.rollback()

    for index, scheduled_id in enumerate(schedule_ids):
        detail = client.get(f"/api/v1/planned-workouts/{scheduled_id}", headers=_headers(token)).get_json()["data"]
        assert client.delete(
            f"/api/v1/mobile/scheduled-workouts/{scheduled_id}",
            headers=_headers(token, f"agenda-cancel-{index}"),
            json={"base_revision": detail["revision"]},
        ).status_code == 200
    archived = client.patch(
        f"/api/v1/mobile/plans/{plan_id}",
        headers=_headers(token, "agenda-archive"),
        json={"base_revision": 3, "status": "archived"},
    )
    assert archived.status_code == 200
    restored = client.patch(
        f"/api/v1/mobile/plans/{plan_id}",
        headers=_headers(token, "agenda-restore"),
        json={"base_revision": 4, "status": "active"},
    )
    assert restored.status_code == 200
    assert restored.get_json()["data"]["status"] == "active"


def test_agenda_query_count_is_bounded(app, client, user):
    with app.app_context():
        owner = User(username="agenda-query-owner-qa", role="user")
        owner.set_password("agenda-query-password")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id
    token = _api_login(
        client,
        username="agenda-query-owner-qa",
        password="agenda-query-password",
        device_id="74444444-4444-4444-8444-444444444444",
    )["access_token"]
    plan_id = _create_plan(client, token, key="agenda-query-plan").get_json()["data"]["public_id"]
    workout_id = str(uuid.uuid4())
    assert client.post(
        f"/api/v1/mobile/plans/{plan_id}/workouts",
        headers=_headers(token, "agenda-query-workout"),
        json={"public_id": workout_id, "base_revision": 1, "name": "Agenda query QA", "exercises": _prescriptions()},
    ).status_code == 201
    for index in range(5):
        assert client.post(
            f"/api/v1/mobile/workouts/{workout_id}/schedule",
            headers=_headers(token, f"agenda-query-{index}"),
            json={"public_id": str(uuid.uuid4()), "scheduled_for_date": f"2028-03-{index + 1:02d}", "timezone": "UTC"},
        ).status_code == 201

    with app.app_context():
        statements = []

        def count_query(*_args):
            statements.append(1)

        event.listen(db.engine, "before_cursor_execute", count_query)
        try:
            records = PlannedWorkoutService.list_range(
                owner_id,
                __import__("datetime").date(2028, 3, 1),
                __import__("datetime").date(2028, 3, 31),
            )
            serialized = [serialize_planned_workout(item) for item in records]
        finally:
            event.remove(db.engine, "before_cursor_execute", count_query)
        assert len(serialized) == 5
        assert len(statements) <= 3


def test_mobile_planning_migration_backfills_and_is_reversible(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260724_0030_mobile_planning.py"
    spec = importlib.util.spec_from_file_location("mobile_planning_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'planning.db'}")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    plans = sa.Table(
        "training_plans",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("active_version_number", sa.Integer(), nullable=False),
    )
    versions = sa.Table(
        "training_plan_versions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("training_plan_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
    )
    metadata.create_all(engine)
    document = {
        "data": {
            "weeks": [{"days": [{"name": "Día QA", "exercises": []}]}]
        }
    }
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
        connection.execute(plans.insert(), {"id": 1, "user_id": 1, "active_version_number": 1})
        connection.execute(
            versions.insert(),
            {"user_id": 1, "training_plan_id": 1, "version_number": 1, "content": document},
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    inspector = sa.inspect(engine)
    assert "training_plan_workouts" in inspector.get_table_names()
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT name FROM training_plan_workouts")).scalar_one() == "Día QA"
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    assert "training_plan_workouts" not in sa.inspect(engine).get_table_names()
    engine.dispose()
