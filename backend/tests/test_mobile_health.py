import json
import importlib.util
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy import event

from app.extensions import db
from app.api_v1.rate_limit import rate_limiter
from app.models import DailyEnergy, User, WeighIn
from tests.test_mobile_sync import _api_login, _auth


DAY = "2026-07-26"


@pytest.fixture(autouse=True)
def clear_mobile_health_rate_limiter():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def _headers(token, key=None):
    headers = _auth(token)
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _token(client):
    return _api_login(client)["access_token"]


def _body_payload(**changes):
    payload = {
        "public_id": str(uuid.uuid4()),
        "recorded_at": "2026-07-26T08:15:00-06:00",
        "weight": "154.324",
        "unit": "lb",
        "body_fat_percent": "19.5",
        "notes": "Fixture corporal QA ficticia",
    }
    payload.update(changes)
    if "weight_kg" in changes:
        payload.pop("weight", None)
        payload.pop("unit", None)
    return payload


def _nutrition_payload(**changes):
    payload = {
        "public_id": str(uuid.uuid4()),
        "date": DAY,
        "meal_type": "breakfast",
        "name": "Avena QA ficticia",
        "quantity": "80",
        "unit": "g",
        "calories_kcal": "300",
        "protein_g": "12",
        "total_carbs_g": "48",
        "fat_g": "7",
        "fiber_g": "6",
    }
    payload.update(changes)
    return payload


def _validator(app):
    schema = json.loads(Path(app.config["SCHEMA_ROOT"], "mobile_health.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _second_token(app, client):
    with app.app_context():
        account = User(username="mobile-health-other", role="user")
        account.set_password("qa-password")
        db.session.add(account)
        db.session.commit()
    return _api_login(
        client,
        username="mobile-health-other",
        password="qa-password",
        device_id="72222222-2222-4222-8222-222222222222",
    )["access_token"]


def test_empty_today_nutrition_and_timezone_contract(app, client, user):
    token = _token(client)
    assert client.get(f"/api/v1/mobile/health/today?date={DAY}").status_code == 401

    today = client.get(
        f"/api/v1/mobile/health/today?date={DAY}&timezone=America%2FMexico_City",
        headers=_headers(token),
    )
    assert today.status_code == 200
    data = today.get_json()["data"]
    assert data["date"] == DAY
    assert data["timezone"] == "America/Mexico_City"
    assert data["weight"] is None
    assert data["nutrition"]["totals"] == {
        "calories_kcal": None, "protein_g": None, "carbohydrate_g": None,
        "fat_g": None, "fiber_g": None,
    }
    assert data["steps"]["value"] is None
    _validator(app).validate(data)

    nutrition = client.get(f"/api/v1/mobile/nutrition/days/{DAY}", headers=_headers(token))
    assert nutrition.status_code == 200
    assert nutrition.get_json()["data"]["meals"] == []
    _validator(app).validate(nutrition.get_json()["data"])
    assert client.get(
        f"/api/v1/mobile/health/today?date={DAY}&timezone=Mars%2FBase",
        headers=_headers(token),
    ).status_code == 400


def test_body_crud_lb_conversion_idempotency_revision_and_rollback(app, client, user):
    token = _token(client)
    payload = _body_payload()
    first = client.post(
        "/api/v1/mobile/body-stats", json=payload, headers=_headers(token, "body-create-qa")
    )
    replay = client.post(
        "/api/v1/mobile/body-stats", json=payload, headers=_headers(token, "body-create-qa")
    )
    assert first.status_code == replay.status_code == 201
    body = first.get_json()["data"]
    assert body == replay.get_json()["data"]
    assert body["weight_kg"] == "70"
    _validator(app).validate(body)

    public_id = body["id"]
    stale = client.patch(
        f"/api/v1/mobile/body-stats/{public_id}",
        json={"base_revision": 99, "weight_kg": "71"},
        headers=_headers(token, "body-stale-qa"),
    )
    assert stale.status_code == 409
    listed = client.get("/api/v1/mobile/body-stats", headers=_headers(token)).get_json()["data"]
    assert listed["items"][0]["weight_kg"] == "70"

    updated = client.patch(
        f"/api/v1/mobile/body-stats/{public_id}",
        json={"base_revision": 1, "weight_kg": "71.25", "notes": None},
        headers=_headers(token, "body-update-qa"),
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["revision"] == 2
    deleted = client.delete(
        f"/api/v1/mobile/body-stats/{public_id}",
        json={"base_revision": 2},
        headers=_headers(token, "body-delete-qa"),
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["data"]["deleted"] is True
    assert client.get("/api/v1/mobile/body-stats", headers=_headers(token)).get_json()["data"]["items"] == []


def test_body_validation_pagination_and_owner_404(app, client, user):
    token = _token(client)
    other = _second_token(app, client)
    created_ids = []
    for index in range(3):
        payload = _body_payload(
            recorded_at=f"2026-07-2{index + 1}T08:00:00Z",
            weight_kg=str(70 + index),
        )
        response = client.post(
            "/api/v1/mobile/body-stats", json=payload,
            headers=_headers(token, f"body-page-{index}"),
        )
        assert response.status_code == 201
        created_ids.append(response.get_json()["data"]["id"])
    first = client.get("/api/v1/mobile/body-stats?limit=2", headers=_headers(token)).get_json()["data"]
    second = client.get(
        f"/api/v1/mobile/body-stats?limit=2&cursor={first['next_cursor']}", headers=_headers(token)
    ).get_json()["data"]
    assert len(first["items"]) == 2 and first["has_more"] is True
    assert len(second["items"]) == 1 and second["has_more"] is False
    assert client.get("/api/v1/mobile/body-stats?limit=0", headers=_headers(token)).status_code == 400
    assert client.post(
        "/api/v1/mobile/body-stats",
        json=_body_payload(weight="0"),
        headers=_headers(token, "body-invalid"),
    ).status_code == 400
    assert client.patch(
        f"/api/v1/mobile/body-stats/{created_ids[0]}",
        json={"base_revision": 1, "weight_kg": "80"},
        headers=_headers(other, "body-other"),
    ).status_code == 404


def test_nutrition_crud_totals_incomplete_duplicate_move_and_delete(app, client, user):
    token = _token(client)
    created = client.post(
        "/api/v1/mobile/nutrition/entries",
        json=_nutrition_payload(),
        headers=_headers(token, "nutrition-create"),
    )
    assert created.status_code == 201
    entry = created.get_json()["data"]
    assert entry["data_complete"] is True
    _validator(app).validate(entry)

    incomplete = client.post(
        "/api/v1/mobile/nutrition/entries",
        json=_nutrition_payload(
            public_id=str(uuid.uuid4()), name="Fruta QA ficticia", calories_kcal="90",
            protein_g=None, total_carbs_g=None, fat_g=None,
        ),
        headers=_headers(token, "nutrition-incomplete"),
    )
    assert incomplete.status_code == 201
    assert incomplete.get_json()["data"]["data_complete"] is False

    day = client.get(f"/api/v1/mobile/nutrition/days/{DAY}", headers=_headers(token)).get_json()["data"]
    assert day["totals"]["calories_kcal"] == "390"
    assert day["totals"]["protein_g"] == "12"
    _validator(app).validate(day)

    updated = client.patch(
        f"/api/v1/mobile/nutrition/entries/{entry['id']}",
        json={"base_revision": 1, "meal_type": "lunch", "calories_kcal": "310"},
        headers=_headers(token, "nutrition-update"),
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["meal_type"] == "lunch"
    duplicate_id = str(uuid.uuid4())
    duplicated = client.post(
        f"/api/v1/mobile/nutrition/entries/{entry['id']}/duplicate",
        json={"public_id": duplicate_id, "meal_type": "dinner"},
        headers=_headers(token, "nutrition-duplicate"),
    )
    assert duplicated.status_code == 201
    assert duplicated.get_json()["data"]["id"] == duplicate_id

    stale = client.patch(
        f"/api/v1/mobile/nutrition/entries/{entry['id']}",
        json={"base_revision": 1, "name": "No debe persistir"},
        headers=_headers(token, "nutrition-stale"),
    )
    assert stale.status_code == 409
    removed = client.delete(
        f"/api/v1/mobile/nutrition/entries/{entry['id']}",
        json={"base_revision": 2},
        headers=_headers(token, "nutrition-delete"),
    )
    assert removed.status_code == 200
    assert removed.get_json()["data"]["deleted"] is True


def test_food_catalog_search_pagination_archive_and_ownership(app, client, user):
    token = _token(client)
    other = _second_token(app, client)
    ids = []
    for index, name in enumerate(("Avena QA", "Arroz QA", "Yogur QA")):
        response = client.post(
            "/api/v1/mobile/foods",
            json={
                "public_id": str(uuid.uuid4()), "name": name,
                "serving_size_g": "100", "serving_label": "100 g",
                "calories_per_100g": str(100 + index), "protein_g_per_100g": "10",
                "carbs_g_per_100g": "20", "fat_g_per_100g": "5",
            },
            headers=_headers(token, f"food-create-{index}"),
        )
        assert response.status_code == 201
        ids.append(response.get_json()["data"]["id"])
        _validator(app).validate(response.get_json()["data"])

    search = client.get("/api/v1/mobile/foods?search=ave", headers=_headers(token)).get_json()["data"]
    assert [item["name"] for item in search["items"]] == ["Avena QA"]
    first = client.get("/api/v1/mobile/foods?limit=2", headers=_headers(token)).get_json()["data"]
    second = client.get(
        f"/api/v1/mobile/foods?limit=2&cursor={first['next_cursor']}", headers=_headers(token)
    ).get_json()["data"]
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert client.patch(
        f"/api/v1/mobile/foods/{ids[0]}",
        json={"base_revision": 1, "name": "Privado"},
        headers=_headers(other, "food-other"),
    ).status_code == 404
    archived = client.patch(
        f"/api/v1/mobile/foods/{ids[0]}",
        json={"base_revision": 1, "archived": True},
        headers=_headers(token, "food-archive"),
    )
    assert archived.status_code == 200 and archived.get_json()["data"]["archived"] is True
    visible_ids = {row["id"] for row in client.get("/api/v1/mobile/foods", headers=_headers(token)).get_json()["data"]["items"]}
    assert ids[0] not in visible_ids


def test_steps_crud_source_coexistence_precedence_ranges_and_idempotency(app, client, user):
    token = _token(client)
    with app.app_context():
        imported = DailyEnergy(user_id=user, date=date.fromisoformat(DAY), steps=7000, source="import")
        db.session.add(imported)
        db.session.commit()

    payload = {"public_id": str(uuid.uuid4()), "date": DAY, "steps": 8500, "source": "manual"}
    first = client.post("/api/v1/mobile/steps", json=payload, headers=_headers(token, "steps-create"))
    replay = client.post("/api/v1/mobile/steps", json=payload, headers=_headers(token, "steps-create"))
    assert first.status_code == replay.status_code == 201
    assert first.get_json()["data"] == replay.get_json()["data"]
    step = first.get_json()["data"]
    _validator(app).validate(step)
    listing = client.get(
        f"/api/v1/mobile/steps?from={DAY}&to={DAY}", headers=_headers(token)
    ).get_json()["data"]["items"]
    assert {(item["source"], item["steps"]) for item in listing} == {("manual", 8500), ("import", 7000)}
    today = client.get(f"/api/v1/mobile/health/today?date={DAY}", headers=_headers(token)).get_json()["data"]
    assert today["steps"]["value"] == 8500 and today["steps"]["source"] == "manual"

    updated = client.patch(
        f"/api/v1/mobile/steps/{step['id']}",
        json={"base_revision": 1, "steps": 9100},
        headers=_headers(token, "steps-update"),
    )
    assert updated.status_code == 200 and updated.get_json()["data"]["steps"] == 9100
    assert client.patch(
        f"/api/v1/mobile/steps/{step['id']}",
        json={"base_revision": 1, "steps": 1},
        headers=_headers(token, "steps-stale"),
    ).status_code == 409
    assert client.get(
        "/api/v1/mobile/steps?from=2025-01-01&to=2026-07-26", headers=_headers(token)
    ).status_code == 400
    assert client.delete(
        f"/api/v1/mobile/steps/{step['id']}", json={"base_revision": 2},
        headers=_headers(token, "steps-delete"),
    ).status_code == 200


def test_complete_today_progress_timezone_and_bounded_query_count(app, client, user):
    token = _token(client)
    body = client.post(
        "/api/v1/mobile/body-stats",
        json=_body_payload(recorded_at="2026-07-27T00:30:00+02:00", weight_kg="72"),
        headers=_headers(token, "complete-body"),
    )
    assert body.status_code == 201
    nutrition = client.post(
        "/api/v1/mobile/nutrition/entries", json=_nutrition_payload(),
        headers=_headers(token, "complete-food"),
    )
    assert nutrition.status_code == 201
    assert client.post(
        "/api/v1/mobile/steps",
        json={"public_id": str(uuid.uuid4()), "date": DAY, "steps": 6200},
        headers=_headers(token, "complete-steps"),
    ).status_code == 201

    statements = []
    with app.app_context():
        engine = db.engine
        listener = lambda *args: statements.append(args[2])
        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = client.get(
                f"/api/v1/mobile/health/today?date={DAY}&timezone=America%2FMexico_City",
                headers=_headers(token),
            )
        finally:
            event.remove(engine, "before_cursor_execute", listener)
    assert response.status_code == 200
    today = response.get_json()["data"]
    assert today["weight_is_exact_date"] is True
    assert today["nutrition"]["totals"]["calories_kcal"] == "300"
    assert today["steps"]["value"] == 6200
    assert len(statements) <= 10
    _validator(app).validate(today)

    progress = client.get(
        f"/api/v1/mobile/health/progress?from={DAY}&to={DAY}&timezone=America%2FMexico_City",
        headers=_headers(token),
    )
    assert progress.status_code == 200
    point = progress.get_json()["data"]["points"][0]
    assert point == {
        "date": DAY, "weight_kg": "72", "steps": 6200,
        "calories_kcal": "300", "protein_g": "12",
        "carbohydrate_g": "48", "fat_g": "7",
    }
    _validator(app).validate(progress.get_json()["data"])


def test_foreign_nutrition_and_step_are_hidden(app, client, user):
    token = _token(client)
    other = _second_token(app, client)
    entry = client.post(
        "/api/v1/mobile/nutrition/entries", json=_nutrition_payload(),
        headers=_headers(token, "owner-entry"),
    ).get_json()["data"]
    step = client.post(
        "/api/v1/mobile/steps",
        json={"public_id": str(uuid.uuid4()), "date": DAY, "steps": 4000},
        headers=_headers(token, "owner-step"),
    ).get_json()["data"]
    assert client.patch(
        f"/api/v1/mobile/nutrition/entries/{entry['id']}",
        json={"base_revision": 1, "name": "Ajeno"},
        headers=_headers(other, "other-entry"),
    ).status_code == 404
    assert client.delete(
        f"/api/v1/mobile/steps/{step['id']}", json={"base_revision": 1},
        headers=_headers(other, "other-step"),
    ).status_code == 404
    assert client.get(f"/api/v1/mobile/nutrition/days/{DAY}", headers=_headers(other)).get_json()["data"]["meals"] == []


def test_public_ids_are_unique_and_schema_is_current(app, client, user):
    schema = _validator(app)
    assert schema.is_valid({
        "id": str(uuid.uuid4()), "date": DAY, "steps": 0, "source": "manual",
        "goal": None, "revision": 1,
        "created_at": "2026-07-26T00:00:00Z", "updated_at": "2026-07-26T00:00:00Z",
    })
    with app.app_context():
        first = WeighIn(
            user_id=user, public_id=str(uuid.uuid4()), recorded_at=datetime.now(timezone.utc),
            weight_kg="70", source="manual",
        )
        db.session.add(first)
        db.session.commit()
        assert first.revision == 1


def test_health_identity_migration_upgrade_and_downgrade_are_reversible(tmp_path):
    migration_path = Path(__file__).parents[1] / "migrations" / "versions" / "20260726_0031_mobile_health_logging.py"
    spec = importlib.util.spec_from_file_location("mobile_health_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'health-migration.db'}")
    metadata = sa.MetaData()
    sa.Table("weigh_ins", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table(
        "daily_energy", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.UniqueConstraint("user_id", "date", name="uq_daily_energy_user_date"),
    )
    sa.Table("nutrition_items", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("food_products", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        for table in ("weigh_ins", "nutrition_items", "food_products"):
            connection.execute(sa.text(f"INSERT INTO {table} (id) VALUES (1)"))
        connection.execute(sa.text("INSERT INTO daily_energy (id,user_id,date,source) VALUES (1,1,'2026-07-26','manual')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    inspector = sa.inspect(engine)
    for table in ("weigh_ins", "daily_energy", "nutrition_items", "food_products"):
        columns = {item["name"] for item in inspector.get_columns(table)}
        assert {"public_id", "revision"} <= columns
        with engine.connect() as connection:
            public_id, revision = connection.execute(sa.text(f"SELECT public_id,revision FROM {table}")).one()
        assert len(public_id) == 36 and revision == 1
    assert {"created_at", "updated_at"} <= {item["name"] for item in inspector.get_columns("nutrition_items")}

    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    inspector = sa.inspect(engine)
    assert "public_id" not in {item["name"] for item in inspector.get_columns("weigh_ins")}
    assert any(item["column_names"] == ["user_id", "date"] for item in inspector.get_unique_constraints("daily_energy"))
    engine.dispose()
