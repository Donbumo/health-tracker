"""Recorrido Alpha 1.5 completo con fixtures QA y limpieza por transacción de pytest."""

import uuid

from app.extensions import db
from app.models import DailyEnergy, NutritionItem, User, WeighIn
from tests.test_companion_protocol import (
    _auth,
    _delivery,
    _login,
    _negotiate,
    _operation,
    _plan,
    _planned,
    _result,
)


DAY = "2026-08-20"


def _key(headers, value):
    return {**headers, "Idempotency-Key": value}


def test_alpha15_real_journey_is_idempotent_owned_and_self_cleaning(app, client, user):
    plan_id, version_id = _plan(app, user)
    initial = _login(client)
    refreshed_response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": initial["refresh_token"]}
    )
    assert refreshed_response.status_code == 200
    refreshed = refreshed_response.get_json()["data"]
    headers = _auth(refreshed["access_token"])
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    assert client.get("/api/v1/devices", headers=headers).status_code == 200

    assert _negotiate(client, headers).status_code == 201
    assert client.get("/api/v1/sync/bootstrap", headers=headers).status_code == 200
    planned = _planned(client, headers, plan_id, version_id)
    assert client.get(
        f"/api/v1/mobile/health/today?date={DAY}&timezone=America%2FMexico_City",
        headers=headers,
    ).status_code == 200
    delivery = _delivery(client, headers, planned["id"], "journey-delivery")
    package = client.get(
        f"/api/v1/companion/deliveries/{delivery['id']}/package", headers=headers
    )
    assert package.status_code == 200
    assert package.get_json()["data"]["package_hash"] == delivery["package_hash"]
    assert _operation(
        client, headers, delivery, "ack", 1,
        received_at="2026-08-20T10:00:00Z", package_hash=delivery["package_hash"],
    ).status_code == 200
    assert _operation(client, headers, delivery, "start", 2).status_code == 200

    progress_event = str(uuid.uuid4())
    progress = {
        "schema_version": "1.0", "client_event_id": progress_event,
        "client_sequence": 1, "event_type": "set_completed",
        "occurred_at": "2026-08-20T12:10:00Z",
        "payload": {"exercise_order": 1, "set_number": 1, "completed_reps": 5},
    }
    progress_url = f"/api/v1/companion/deliveries/{delivery['id']}/progress"
    assert client.post(progress_url, headers=_key(headers, "journey-progress-a"), json=progress).status_code == 201
    replay = client.post(progress_url, headers=_key(headers, "journey-progress-b"), json=progress)
    assert replay.status_code == 200 and replay.get_json()["data"]["duplicate"] is True

    completion_event = str(uuid.uuid4())
    completion = {
        "schema_version": "1.0", "client_event_id": completion_event,
        "package_hash": delivery["package_hash"], "base_revision": 3,
        "result": _result(planned["id"], completion_event),
    }
    complete_url = f"/api/v1/companion/deliveries/{delivery['id']}/complete"
    created = client.post(complete_url, headers=_key(headers, "journey-complete-a"), json=completion)
    repeated = client.post(complete_url, headers=_key(headers, "journey-complete-b"), json=completion)
    assert created.status_code == 201 and repeated.status_code == 200
    assert created.get_json()["data"]["completed_workout"]["id"] == repeated.get_json()["data"]["completed_workout"]["id"]
    assert client.get("/api/v1/mobile/history?limit=10", headers=headers).status_code == 200
    assert client.get("/api/v1/mobile/progress/summary?range=30", headers=headers).status_code == 200

    body_event, nutrition_event, steps_event = (str(uuid.uuid4()) for _ in range(3))
    body_payload = {
        "public_id": str(uuid.uuid4()), "client_event_id": body_event,
        "recorded_at": "2026-08-20T08:00:00-06:00", "weight_kg": "70.2",
        "source": "health_connect", "notes": "Fixture QA Alpha 1.5",
    }
    body = client.post("/api/v1/mobile/body-stats", headers=_key(headers, "journey-body-a"), json=body_payload)
    body_replay = client.post(
        "/api/v1/mobile/body-stats", headers=_key(headers, "journey-body-b"),
        json={**body_payload, "public_id": str(uuid.uuid4())},
    )
    assert body.status_code == body_replay.status_code == 201
    body_data = body.get_json()["data"]
    assert body_data["id"] == body_replay.get_json()["data"]["id"]

    nutrition_payload = {
        "public_id": str(uuid.uuid4()), "client_event_id": nutrition_event,
        "date": DAY, "meal_type": "breakfast", "name": "Avena QA ficticia",
        "calories_kcal": "300", "protein_g": "12", "total_carbs_g": "48",
        "fat_g": "7", "source": "health_connect",
    }
    nutrition = client.post(
        "/api/v1/mobile/nutrition/entries", headers=_key(headers, "journey-nutrition-a"), json=nutrition_payload,
    )
    nutrition_replay = client.post(
        "/api/v1/mobile/nutrition/entries", headers=_key(headers, "journey-nutrition-b"),
        json={**nutrition_payload, "public_id": str(uuid.uuid4())},
    )
    assert nutrition.status_code == nutrition_replay.status_code == 201
    nutrition_data = nutrition.get_json()["data"]
    assert nutrition_data["id"] == nutrition_replay.get_json()["data"]["id"]

    steps_payload = {
        "public_id": str(uuid.uuid4()), "client_event_id": steps_event,
        "date": DAY, "steps": 4321, "source": "health_connect_aggregate",
    }
    steps = client.post("/api/v1/mobile/steps", headers=_key(headers, "journey-steps-a"), json=steps_payload)
    steps_replay = client.post(
        "/api/v1/mobile/steps", headers=_key(headers, "journey-steps-b"),
        json={**steps_payload, "public_id": str(uuid.uuid4())},
    )
    assert steps.status_code == steps_replay.status_code == 201
    steps_data = steps.get_json()["data"]
    assert steps_data["id"] == steps_replay.get_json()["data"]["id"]

    with app.app_context():
        other = User(username="alpha15-journey-other", role="user")
        other.set_password("qa-password")
        db.session.add(other)
        db.session.commit()
    other_headers = _auth(_login(
        client, "alpha15-journey-other", "qa-password", "89999999-9999-4999-8999-999999999999"
    )["access_token"])
    assert client.patch(
        f"/api/v1/mobile/body-stats/{body_data['id']}", headers=_key(other_headers, "foreign-body"),
        json={"base_revision": 1, "weight_kg": "99"},
    ).status_code == 404

    body_updated = client.patch(
        f"/api/v1/mobile/body-stats/{body_data['id']}", headers=_key(headers, "journey-body-update"),
        json={"base_revision": 1, "source": "user_override", "weight_kg": "70.3"},
    ).get_json()["data"]
    nutrition_updated = client.patch(
        f"/api/v1/mobile/nutrition/entries/{nutrition_data['id']}",
        headers=_key(headers, "journey-nutrition-update"),
        json={"base_revision": 1, "source": "user_override", "name": "Avena QA revisada"},
    ).get_json()["data"]
    steps_updated = client.patch(
        f"/api/v1/mobile/steps/{steps_data['id']}", headers=_key(headers, "journey-steps-update"),
        json={"base_revision": 1, "steps": 4322},
    ).get_json()["data"]
    assert client.delete(
        f"/api/v1/mobile/body-stats/{body_data['id']}", headers=_key(headers, "journey-body-delete"),
        json={"base_revision": body_updated["revision"]},
    ).status_code == 200
    assert client.delete(
        f"/api/v1/mobile/nutrition/entries/{nutrition_data['id']}",
        headers=_key(headers, "journey-nutrition-delete"),
        json={"base_revision": nutrition_updated["revision"]},
    ).status_code == 200
    assert client.delete(
        f"/api/v1/mobile/steps/{steps_data['id']}", headers=_key(headers, "journey-steps-delete"),
        json={"base_revision": steps_updated["revision"]},
    ).status_code == 200
    with app.app_context():
        assert db.session.execute(db.select(WeighIn).where(WeighIn.client_event_id == body_event)).scalar_one_or_none() is None
        assert db.session.execute(db.select(NutritionItem).where(NutritionItem.client_event_id == nutrition_event)).scalar_one_or_none() is None
        assert db.session.execute(db.select(DailyEnergy).where(DailyEnergy.client_event_id == steps_event)).scalar_one_or_none() is None
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/me", headers=headers).status_code == 401
