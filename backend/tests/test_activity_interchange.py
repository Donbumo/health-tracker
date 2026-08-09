from __future__ import annotations

from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import io
import importlib.util
import json
from pathlib import Path
import shutil
from threading import Barrier
import uuid
from zipfile import ZipFile

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator, FormatChecker

from app import create_app
from app.api_v1.rate_limit import rate_limiter
from app.extensions import db
from app.models import Activity, ActivityImportJob, PlannedWorkout, TrainingPlan, TrainingPlanVersion, UploadedFile, User
from app.services.activity_interchange import cleanup_expired_import_jobs, deterministic_downsample, redact_route
from app.services.activity_parsers import ActivityParseError, ActivityParserRegistry


DEVICE_ID = "a2000000-0000-4000-8000-000000000001"
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "qa" / "real-file-imports"


@pytest.fixture(autouse=True)
def clear_rate_limits():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def _gpx(*, timestamps=True, segments=1, xxe=False, deep=0):
    if xxe:
        return b'<!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file:///qa-secret">]><gpx>&xxe;</gpx>'
    prefix = "<qa>" * deep
    suffix = "</qa>" * deep
    chunks = []
    for segment in range(segments):
        points = []
        for index in range(3):
            moment = f"<time>2026-07-31T10:0{segment * 3 + index}:00Z</time>" if timestamps else ""
            # QA-only coordinates in the open ocean; not a personal or real route.
            points.append(f'<trkpt lat="0.00{segment}{index + 1}" lon="-140.00{segment}{index + 1}"><ele>{index}</ele>{moment}</trkpt>')
        chunks.append(f"<trkseg>{''.join(points)}</trkseg>")
    return f'<?xml version="1.0"?><gpx version="1.1" creator="Health Tracker QA"><metadata><name>RUTA SINTETICA QA</name></metadata>{prefix}<trk>{"".join(chunks)}</trk>{suffix}</gpx>'.encode()


def _tcx():
    return b'''<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"><Activities><Activity Sport="Biking"><Id>2026-07-31T10:00:00Z</Id><Lap StartTime="2026-07-31T10:00:00Z"><Track><Trackpoint><Time>2026-07-31T10:00:00Z</Time><Position><LatitudeDegrees>0.001</LatitudeDegrees><LongitudeDegrees>-140.001</LongitudeDegrees></Position><HeartRateBpm><Value>120</Value></HeartRateBpm><Cadence>80</Cadence></Trackpoint><Trackpoint><Time>2026-07-31T10:01:00Z</Time><Position><LatitudeDegrees>0.002</LatitudeDegrees><LongitudeDegrees>-140.002</LongitudeDegrees></Position><HeartRateBpm><Value>124</Value></HeartRateBpm><Cadence>82</Cadence></Trackpoint></Track></Lap></Activity></Activities></TrainingCenterDatabase>'''


def _login(client, username="test-user", password="test-password", device=DEVICE_ID):
    response = client.post("/api/v1/auth/login", json={
        "email": username, "password": password,
        "device": {"device_id": device, "name": "Dispositivo QA ficticio", "platform": "android", "app_version": "2.0.0-alpha01", "os_version": "QA"},
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.get_json()['data']['access_token']}"}


def _upload(client, auth, content=None, filename="activity.gpx", key="activity-upload-key-0001", **form):
    data = {"file": (io.BytesIO(content if content is not None else _gpx()), filename), "route_policy": form.get("route_policy", "keep")}
    if "redact_start_meters" in form:
        data["redact_start_meters"] = str(form["redact_start_meters"])
        data["redact_end_meters"] = str(form.get("redact_end_meters", 0))
    if form.get("planned_workout_id"):
        data["planned_workout_id"] = form["planned_workout_id"]
    return client.post("/api/v1/mobile/activities/imports", data=data, headers={**auth, "Idempotency-Key": key}, content_type="multipart/form-data")


def _apply(client, auth, import_id, key="activity-apply-key-0001"):
    inspected = client.post(f"/api/v1/mobile/activities/imports/{import_id}/inspect", headers=auth)
    assert inspected.status_code == 200, inspected.get_json()
    return client.post(f"/api/v1/mobile/activities/imports/{import_id}/apply", json={"confirm": True}, headers={**auth, "Idempotency-Key": key})


def _planned(app, user_id):
    with app.app_context():
        plan = TrainingPlan(user_id=user_id, name="Plan ciclismo QA", active_version_number=1)
        db.session.add(plan); db.session.flush()
        content = {"schema_version": "1.0", "record_type": "training_plan", "user_id": user_id, "source_type": "manual_generated", "data": {"name": "Plan QA", "weeks": []}}
        version = TrainingPlanVersion(user_id=user_id, training_plan=plan, version_number=1, schema_version="1.0", sha256="a" * 64, content=content)
        db.session.add(version); db.session.flush()
        row = PlannedWorkout(user_id=user_id, training_plan=plan, training_plan_version=version, scheduled_for_date=date(2026, 7, 31), timezone="UTC", title_snapshot="Ciclismo QA", payload_snapshot_json={"estimated_duration_seconds": 3600, "sets": [{"duration_seconds": 900}, {"duration_seconds": 900}]}, source_version=1)
        db.session.add(row); db.session.commit()
        return row.public_id


@pytest.mark.parametrize("content,filename,code", [
    (b"", "empty.gpx", "empty_file"),
    (b"<html>QA</html>", "fake.gpx", "unsafe_file"),
    (b"MZ" + b"0" * 20, "fake.fit", "unsafe_file"),
    (_gpx(xxe=True), "evil.gpx", "invalid_activity_file"),
    (_gpx(deep=70), "deep.gpx", "invalid_activity_file"),
    (b"<TrainingCenterDatabase><Activities>", "corrupt.tcx", "invalid_activity_file"),
])
def test_parser_rejects_empty_false_or_unsafe_files(app, content, filename, code):
    with app.app_context(), pytest.raises(ActivityParseError) as captured:
        ActivityParserRegistry().parse(filename, content)
    assert captured.value.code == code


def test_gpx_multisegment_is_normalized_with_provenance(app):
    with app.app_context():
        parsed = ActivityParserRegistry().parse("qa.gpx", _gpx(segments=2))
    assert parsed.document["format"] == "health-tracker-activity-v1"
    assert parsed.document["summary"]["distance"]["provenance"] == "derived_exact"
    assert parsed.metadata["segments"] == 2
    assert any("segments" in warning for warning in parsed.warnings)
    assert len(parsed.route_points) == 6


def test_gpx_without_timestamps_is_not_silently_invented(app):
    with app.app_context(), pytest.raises(ActivityParseError) as captured:
        ActivityParserRegistry().parse("qa.gpx", _gpx(timestamps=False))
    assert captured.value.code == "missing_timestamps"


def test_activity_upload_size_limit_is_enforced_before_parse(app, client, user):
    auth = _login(client); original = app.config["ACTIVITY_FILE_MAX_BYTES"]
    try:
        app.config["ACTIVITY_FILE_MAX_BYTES"] = 32
        response = _upload(client, auth, content=b"x" * 33, key="oversize-activity-upload")
        assert response.status_code == 413 and response.get_json()["error"]["code"] == "file_too_large"
    finally:
        app.config["ACTIVITY_FILE_MAX_BYTES"] = original


def test_tcx_hr_and_cadence_are_preserved_as_sport_metrics(app):
    with app.app_context():
        parsed = ActivityParserRegistry().parse("qa.tcx", _tcx())
    assert "heart_rate" in parsed.document["sampleSeries"]["fields"]
    assert "cadence" in parsed.document["sampleSeries"]["fields"]
    assert parsed.document["activity"]["discipline"] == "cycling"


def test_fit_valid_truncated_and_out_of_order_are_controlled(app):
    registry = ActivityParserRegistry()
    with app.app_context():
        parsed = registry.parse("qa.fit", (FIXTURE_ROOT / "valid_activity.fit").read_bytes())
        assert parsed.source_format == "fit"
        assert parsed.document["summary"]["duration"]["provenance"] == "source_provided"
        with pytest.raises(ActivityParseError):
            registry.parse("qa.fit", (FIXTURE_ROOT / "truncated.fit").read_bytes())
        generator_path = FIXTURE_ROOT / "generate_fit_fixtures.py"
        spec = importlib.util.spec_from_file_location("activity_fit_generator", generator_path)
        generator = importlib.util.module_from_spec(spec); spec.loader.exec_module(generator)
        out_of_order = registry.parse("qa.fit", generator.valid_activity(out_of_order=True))
        assert any("fuera de orden" in warning for warning in out_of_order.warnings)


def test_redaction_is_deterministic_and_does_not_mutate_original():
    points = [{"lat": 0.0, "lon": -140.000 + index * 0.001, "distance": index * 111.0} for index in range(6)]
    original = json.loads(json.dumps(points))
    first = redact_route(points, 100, 100)
    second = redact_route(points, 100, 100)
    assert first == second
    assert points == original
    assert 0 < len(first) < len(points)


def test_downsampling_keeps_endpoints_and_is_deterministic():
    samples = [{"t": index, "power": 100 + index} for index in range(100)]
    first = deterministic_downsample(samples, 10)
    assert first == deterministic_downsample(samples, 10)
    assert first[0] == samples[0] and first[-1] == samples[-1]
    assert len(first) == 10


def test_activity_schemas_are_valid_and_local_refs_resolve(app):
    root = Path(app.config["SCHEMA_ROOT"])
    for name in ("activity_v1", "activity_summary_v1", "activity_lap_v1", "activity_series_v1", "activity_route_v1", "plan_actual_comparison"):
        schema = json.loads((root / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_import_api_round_trip_series_route_exports_and_exact_dedup(app, client, user):
    auth = _login(client)
    created = _upload(client, auth)
    assert created.status_code == 201, created.get_json()
    import_id = created.get_json()["data"]["import_id"]
    applied = _apply(client, auth, import_id)
    assert applied.status_code == 201, applied.get_json()
    activity_id = applied.get_json()["data"]["activity"]["publicId"]
    detail = client.get(f"/api/v1/mobile/activities/{activity_id}", headers=auth)
    assert detail.status_code == 200
    assert detail.get_json()["data"]["route"]["present"] is True
    series = client.get(f"/api/v1/mobile/activities/{activity_id}/series?limit=2", headers=auth)
    assert series.status_code == 200
    assert len(series.get_json()["data"]["items"]) == 2
    route = client.get(f"/api/v1/mobile/activities/{activity_id}/route", headers=auth)
    assert route.status_code == 200 and len(route.get_json()["data"]["points"]) == 3
    exported = client.get(f"/api/v1/mobile/activities/{activity_id}/export?format=json&include_series=true", headers=auth)
    assert exported.status_code == 200 and json.loads(exported.data)["format"] == "health-tracker-activity-v1"
    summary_csv = client.get(f"/api/v1/mobile/activities/{activity_id}/export?format=csv_summary", headers=auth)
    laps_csv = client.get(f"/api/v1/mobile/activities/{activity_id}/export?format=csv_laps", headers=auth)
    samples_csv = client.get(f"/api/v1/mobile/activities/{activity_id}/export?format=csv_samples&include_series=true", headers=auth)
    assert summary_csv.status_code == laps_csv.status_code == samples_csv.status_code == 200
    assert b"public_id,discipline" in summary_csv.data and b"index,start_time" in laps_csv.data
    blocked = client.get(f"/api/v1/mobile/activities/{activity_id}/export?format=gpx", headers=auth)
    assert blocked.status_code == 400
    gpx = client.get(f"/api/v1/mobile/activities/{activity_id}/export?format=gpx&include_route=true", headers=auth)
    assert gpx.status_code == 200 and b"<time>2026-07-31T10:00:00Z</time>" in gpx.data
    assert gpx.headers["X-Health-Tracker-Export-Warning"]
    revision = detail.get_json()["data"]["revision"]
    removed = client.delete(f"/api/v1/mobile/activities/{activity_id}/route", json={"base_revision": revision},
        headers={**auth, "Idempotency-Key": "remove-route-key"})
    assert removed.status_code == 200 and removed.get_json()["data"]["route"]["present"] is False
    assert client.get(f"/api/v1/mobile/activities/{activity_id}", headers=auth).status_code == 200
    gpx = client.get(f"/api/v1/mobile/activities/{activity_id}/export?format=gpx&include_route=true", headers=auth)
    assert gpx.status_code == 409 and gpx.get_json()["error"]["code"] == "route_unavailable"
    repeated = _upload(client, auth, filename="renamed.gpx", key="activity-upload-key-0002")
    assert repeated.status_code == 201
    assert repeated.get_json()["data"]["duplicate_classification"] == "exact_file_duplicate"
    assert repeated.get_json()["data"]["activity_id"] == activity_id
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(Activity.id))).scalar_one() == 1


def test_import_idempotency_and_conflict(app, client, user):
    auth = _login(client)
    first = _upload(client, auth, key="same-idempotency-key")
    replay = _upload(client, auth, key="same-idempotency-key")
    conflict = _upload(client, auth, content=_tcx(), filename="other.tcx", key="same-idempotency-key")
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.get_json()["data"]["import_id"] == first.get_json()["data"]["import_id"]
    assert conflict.status_code == 409


def test_expired_import_cleanup_removes_owner_job_and_unshared_file(app, client, user):
    auth = _login(client)
    created = _upload(client, auth, key="expired-cleanup-upload")
    assert created.status_code == 201
    with app.app_context():
        job = db.session.execute(db.select(ActivityImportJob).where(
            ActivityImportJob.public_id == created.get_json()["data"]["import_id"])).scalar_one()
        path = Path(app.config["UPLOAD_ROOT"]) / f"user_{user}" / job.uploaded_file.stored_filename
        assert path.is_file()
        job.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc); db.session.commit()
        assert cleanup_expired_import_jobs() == 1
        assert not path.exists()
        assert db.session.execute(db.select(ActivityImportJob).where(ActivityImportJob.public_id == created.get_json()["data"]["import_id"])).scalar_one_or_none() is None


def test_route_drop_and_route_delete_keep_activity(app, client, user):
    auth = _login(client)
    dropped = _upload(client, auth, key="drop-upload-key", route_policy="drop")
    applied = _apply(client, auth, dropped.get_json()["data"]["import_id"], key="drop-apply-key")
    activity_id = applied.get_json()["data"]["activity"]["publicId"]
    route = client.get(f"/api/v1/mobile/activities/{activity_id}/route", headers=auth)
    assert route.get_json()["data"]["present"] is False
    assert client.get(f"/api/v1/mobile/activities/{activity_id}", headers=auth).status_code == 200


def test_route_redaction_stores_visible_copy_separately(app, client, user):
    auth = _login(client)
    created = _upload(client, auth, key="redact-upload-key", route_policy="redact", redact_start_meters=50, redact_end_meters=50)
    applied = _apply(client, auth, created.get_json()["data"]["import_id"], key="redact-apply-key")
    activity_id = applied.get_json()["data"]["activity"]["publicId"]
    with app.app_context():
        row = db.session.execute(db.select(Activity).where(Activity.public_id == activity_id)).scalar_one()
        assert row.route_metadata.original_storage_path != row.route_metadata.visible_storage_path
        assert row.route_metadata.visible_point_count < row.route_metadata.original_point_count


def test_strong_plan_link_and_descriptive_comparison(app, client, user):
    planned_id = _planned(app, user)
    auth = _login(client)
    created = _upload(client, auth, key="strong-upload-key", planned_workout_id=planned_id)
    applied = _apply(client, auth, created.get_json()["data"]["import_id"], key="strong-apply-key")
    activity = applied.get_json()["data"]["activity"]
    assert activity["planLink"]["state"] == "strong_auto_link"
    response = client.get(f"/api/v1/mobile/activities/{activity['publicId']}/comparison", headers=auth)
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] in {"completed", "partially_completed", "deviated", "insufficient_data"}
    assert {"duration", "intervals"} <= set(response.get_json()["data"]["comparisons"])
    assert all("recomend" not in item.casefold() for item in response.get_json()["data"].get("messages", []))


def test_suggested_link_requires_manual_confirmation(app, client, user):
    planned_id = _planned(app, user)
    auth = _login(client)
    created = _upload(client, auth, key="weak-upload-key")
    applied = _apply(client, auth, created.get_json()["data"]["import_id"], key="weak-apply-key")
    activity = applied.get_json()["data"]["activity"]
    assert "planLink" not in activity
    candidates = client.get(f"/api/v1/mobile/activities/{activity['publicId']}/plan-candidates", headers=auth)
    assert any(item["planned_workout_id"] == planned_id for item in candidates.get_json()["data"]["items"])
    rejected = client.post(
        f"/api/v1/mobile/activities/{activity['publicId']}/plan-link",
        json={"base_revision": activity["revision"], "planned_workout_id": planned_id, "action": "reject"},
        headers={**auth, "Idempotency-Key": "manual-reject-key"},
    )
    assert rejected.status_code == 200 and rejected.get_json()["data"]["state"] == "user_rejected"
    revision = client.get(f"/api/v1/mobile/activities/{activity['publicId']}", headers=auth).get_json()["data"]["revision"]
    linked = client.post(
        f"/api/v1/mobile/activities/{activity['publicId']}/plan-link",
        json={"base_revision": revision, "planned_workout_id": planned_id, "action": "confirm"},
        headers={**auth, "Idempotency-Key": "manual-link-key"},
    )
    assert linked.status_code == 200 and linked.get_json()["data"]["state"] == "user_confirmed"


def test_indoor_fit_without_gps_keeps_metrics_without_route(app, client, user):
    auth = _login(client)
    content = (FIXTURE_ROOT / "valid_activity_no_gps.fit").read_bytes()
    created = _upload(client, auth, content=content, filename="fictional-indoor.fit", key="indoor-fit-upload")
    applied = _apply(client, auth, created.get_json()["data"]["import_id"], key="indoor-fit-apply")
    activity = applied.get_json()["data"]["activity"]
    assert activity["route"]["present"] is False
    assert "heart_rate_average" in activity["summary"]
    comparison = client.get(f"/api/v1/mobile/activities/{activity['publicId']}/comparison", headers=auth)
    assert comparison.get_json()["data"]["status"] == "not_comparable"


def test_probable_duplicate_is_preserved_for_user_review(app, client, user):
    auth = _login(client)
    first = _upload(client, auth, key="probable-first-upload")
    assert _apply(client, auth, first.get_json()["data"]["import_id"], key="probable-first-apply").status_code == 201
    changed = _gpx().replace(b'lon="-140.0003"', b'lon="-140.0004"')
    second = _upload(client, auth, content=changed, key="probable-second-upload")
    applied = _apply(client, auth, second.get_json()["data"]["import_id"], key="probable-second-apply")
    assert applied.status_code == 201
    detail = applied.get_json()["data"]["activity"]
    assert detail["duplicateCount"] >= 1
    assert any(row["classification"] in {"probable_duplicate", "possible_duplicate"} for row in detail["duplicates"])


def test_cross_account_activity_and_import_are_404(app, client, user):
    auth = _login(client)
    created = _upload(client, auth, key="owner-upload-key")
    applied = _apply(client, auth, created.get_json()["data"]["import_id"], key="owner-apply-key")
    activity_id = applied.get_json()["data"]["activity"]["publicId"]
    with app.app_context():
        other = User(username="other-activity-user", role="user"); other.set_password("other-password")
        db.session.add(other); db.session.commit()
    other_auth = _login(client, "other-activity-user", "other-password", "a2000000-0000-4000-8000-000000000002")
    assert client.get(f"/api/v1/mobile/activities/{activity_id}", headers=other_auth).status_code == 404
    assert client.get(f"/api/v1/mobile/activities/imports/{created.get_json()['data']['import_id']}", headers=other_auth).status_code == 404


def test_activity_list_uses_bounded_queries_instead_of_n_plus_one(app, client, user):
    with app.app_context():
        for index in range(8):
            db.session.add(Activity(user_id=user, activity_type="cycling", discipline="cycling",
                original_type="cycling", started_at=datetime(2026, 7, 30, index, tzinfo=timezone.utc),
                source_type="uploaded", source_format="gpx", fingerprint_sha256=f"{index + 10:064x}",
                canonical_json={"schema_version": "1.0", "record_type": "activity", "user_id": user,
                    "source_type": "uploaded", "data": {"activity_type": "cycling", "started_at": "2026-07-30T00:00:00Z"}},
                point_count=0, metrics_provenance_json={}, status="imported", revision=1))
        db.session.commit()
    auth = _login(client)
    statements = []
    with app.app_context():
        engine = db.engine
        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"): statements.append(statement)
        sa.event.listen(engine, "before_cursor_execute", capture)
        try:
            response = client.get("/api/v1/mobile/activities?limit=50", headers=auth)
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200 and len(response.get_json()["data"]["items"]) == 8
    assert len(statements) <= 8


def test_invalid_metric_nan_and_coordinate_are_rejected(app):
    payload = {
        "format": "health-tracker-activity-v1", "formatVersion": "1.0",
        "activity": {"publicId": str(uuid.uuid4()), "discipline": "cycling", "originalType": "cycling", "startTime": "2026-07-31T10:00:00Z", "localDate": "2026-07-31", "environment": "outdoor", "status": "ready_to_import", "sourceFormat": "json", "revision": 1},
        "summary": {}, "laps": [], "intervals": [], "sampleSeries": {"format": "activity-series-v1", "sampleCount": 1, "fields": ["power"]},
        "series": {"format": "activity-series-v1", "samples": [{"t": 0, "power": float("nan")}]},
        "route": {"present": True, "points": [{"lat": 95, "lon": 0}]}, "events": [], "sourceReference": {"format": "json"}, "warnings": []
    }
    content = json.dumps(payload).encode()
    with app.app_context(), pytest.raises(ActivityParseError):
        ActivityParserRegistry().parse("qa.json", content)


def test_logs_do_not_include_coordinates_or_full_hash(app, client, user, caplog):
    auth = _login(client)
    created = _upload(client, auth, key="sanitized-log-key")
    _apply(client, auth, created.get_json()["data"]["import_id"], key="sanitized-apply-key")
    text = caplog.text
    assert "-140.00" not in text
    with app.app_context():
        job = db.session.execute(db.select(ActivityImportJob)).scalars().first()
        assert job.uploaded_file.sha256 not in text


def test_activity_portability_requires_explicit_coordinates_and_series_and_round_trips(app, client, user):
    auth = _login(client)
    created = _upload(client, auth, content=_tcx(), filename="portable-activity.tcx", key="portable-activity-upload", route_policy="keep")
    applied = _apply(client, auth, created.get_json()["data"]["import_id"], key="portable-activity-apply")
    source_id = applied.get_json()["data"]["activity"]["publicId"]
    sections = ["activities", "activity_laps"]

    default_export = client.post("/api/v1/mobile/portability/exports", json={"sections": sections},
        headers={**auth, "Idempotency-Key": "portable-activity-default"})
    assert default_export.status_code == 201
    default_package = client.get(f"/api/v1/mobile/portability/exports/{default_export.get_json()['data']['export_id']}/download", headers=auth).data
    with ZipFile(io.BytesIO(default_package)) as archive:
        records = [json.loads(line) for line in archive.read("records/activities.jsonl").splitlines()]
        assert records[0]["data"]["route"]["included"] is False
        assert "records/activity_series.jsonl" not in archive.namelist()

    private_export = client.post("/api/v1/mobile/portability/exports", json={
        "sections": sections, "include_activity_coordinates": True, "include_activity_series": True,
    }, headers={**auth, "Idempotency-Key": "portable-activity-private"})
    assert private_export.status_code == 201, private_export.get_json()
    package = client.get(f"/api/v1/mobile/portability/exports/{private_export.get_json()['data']['export_id']}/download", headers=auth).data
    with ZipFile(io.BytesIO(package)) as archive:
        records = [json.loads(line) for line in archive.read("records/activities.jsonl").splitlines()]
        assert records[0]["data"]["route"]["included"] is True
        assert len(records[0]["data"]["route"]["points"]) == 2
        assert "records/activity_series.jsonl" in archive.namelist()

    with app.app_context():
        destination = User(username="activity-portable-destination", role="user")
        destination.set_password("fictional-password")
        db.session.add(destination); db.session.commit(); destination_id = destination.id
    destination_auth = _login(client, "activity-portable-destination", "fictional-password", "a2000000-0000-4000-8000-000000000099")
    inspected = client.post("/api/v1/mobile/portability/imports/inspect", data={
        "file": (io.BytesIO(package), "fictional-activity.htpack"),
        "sections": json.dumps(["activities", "activity_laps", "activity_series"]),
    }, headers=destination_auth, content_type="multipart/form-data")
    assert inspected.status_code == 201, inspected.get_json()
    import_id = inspected.get_json()["data"]["import_id"]
    imported = client.post(f"/api/v1/mobile/portability/imports/{import_id}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []},
        headers={**destination_auth, "Idempotency-Key": "portable-activity-import"})
    assert imported.status_code == 200, imported.get_json()
    with app.app_context():
        row = db.session.execute(db.select(Activity).where(Activity.user_id == destination_id)).scalar_one()
        assert row.public_id != source_id
        assert len(row.laps) == 1 and row.series_artifact.sample_count == 2
        assert row.route_metadata.visible_point_count == 2


def test_activity_migration_0036_is_additive_reversible_and_reupgradeable(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260731_0036_activity_interchange.py"
    spec = importlib.util.spec_from_file_location("activity_interchange_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.down_revision == "20260731_0035"
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'activity-migration.db'}")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("uploaded_files", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("planned_workouts", metadata, sa.Column("id", sa.Integer(), primary_key=True), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    sa.Table("activities", metadata, sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False), sa.Column("started_at", sa.DateTime(), nullable=False))
    metadata.create_all(engine)
    expected = {"activity_import_jobs", "activity_laps", "activity_series_artifacts", "activity_route_metadata",
        "activity_duplicate_candidates", "plan_activity_links", "plan_actual_comparison_snapshots"}
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO activities (id,user_id,started_at) VALUES (1,1,'2026-07-31 10:00:00')"))
        with Operations.context(MigrationContext.configure(connection)): migration.upgrade()
        assert connection.execute(sa.text("SELECT COUNT(*) FROM activities WHERE id=1")).scalar_one() == 1
    assert expected <= set(sa.inspect(engine).get_table_names())
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)): migration.downgrade()
    assert expected.isdisjoint(sa.inspect(engine).get_table_names())
    assert "public_id" not in {row["name"] for row in sa.inspect(engine).get_columns("activities")}
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)): migration.upgrade()
    assert expected <= set(sa.inspect(engine).get_table_names())
    engine.dispose()


@pytest.mark.skipif(not Path("/.dockerenv").exists(), reason="MariaDB activity concurrency runs only in Docker")
def test_mariadb_concurrent_activity_upload_replays_one_job(app, tmp_path):
    concurrent_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "activity-mariadb-secret-long-enough",
        "API_TOKEN_SIGNING_KEY": "activity-mariadb-api-key-long-enough",
        "DATA_ROOT": tmp_path / "mariadb-activities",
        "UPLOAD_ROOT": tmp_path / "mariadb-activities" / "uploads" / "raw",
        "GENERATED_UPLOAD_ROOT": tmp_path / "mariadb-activities" / "uploads" / "generated",
        "PORTABILITY_ROOT": tmp_path / "mariadb-activities" / "portability",
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC", "WTF_CSRF_ENABLED": False, "API_RATE_LIMIT_ENABLED": False,
    })
    username = f"activity-race-{uuid.uuid4().hex}"
    with concurrent_app.app_context():
        account = User(username=username, email=f"{username}@example.invalid", role="user")
        account.set_password("fictional-race-password")
        db.session.add(account); db.session.commit(); account_id = account.id
    try:
        login_client = concurrent_app.test_client()
        token = _login(login_client, username, "fictional-race-password")["Authorization"]
        barrier = Barrier(2)

        def upload_once():
            with concurrent_app.test_client() as race_client:
                barrier.wait(timeout=10)
                response = race_client.post("/api/v1/mobile/activities/imports", data={
                    "file": (io.BytesIO(_gpx()), "fictional-concurrent.gpx"), "route_policy": "drop",
                }, content_type="multipart/form-data", headers={
                    "Authorization": token, "Idempotency-Key": "activity-concurrent-upload",
                })
                return response.status_code, response.get_json()["data"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: upload_once(), range(2)))
        assert sorted(status for status, _data in results) == [200, 201]
        assert len({data["import_id"] for _status, data in results}) == 1
        with concurrent_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(ActivityImportJob).where(
                ActivityImportJob.user_id == account_id)) == 1
            assert db.session.scalar(db.select(db.func.count()).select_from(UploadedFile).where(
                UploadedFile.user_id == account_id)) == 1
    finally:
        with concurrent_app.app_context():
            account = db.session.get(User, account_id)
            if account is not None:
                db.session.delete(account)
            db.session.commit()


@pytest.mark.skipif(not Path("/.dockerenv").exists(), reason="MariaDB activity E2E runs only in Docker")
def test_mariadb_activity_fit_gpx_plan_portability_e2e(app, tmp_path):
    storage_root = tmp_path / "mariadb-activity-e2e"
    e2e_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "activity-e2e-secret-key-that-is-long-enough",
        "API_TOKEN_SIGNING_KEY": "activity-e2e-api-key-long-enough",
        "DATA_ROOT": storage_root,
        "UPLOAD_ROOT": storage_root / "uploads" / "raw",
        "GENERATED_UPLOAD_ROOT": storage_root / "uploads" / "generated",
        "PORTABILITY_ROOT": storage_root / "portability",
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC", "WTF_CSRF_ENABLED": False, "API_RATE_LIMIT_ENABLED": False,
    })
    source_name = f"activity-e2e-source-{uuid.uuid4().hex}"
    destination_name = f"activity-e2e-destination-{uuid.uuid4().hex}"
    with e2e_app.app_context():
        source = User(username=source_name, email=f"{source_name}@example.invalid", role="user")
        source.set_password("fictional-e2e-password")
        destination = User(username=destination_name, email=f"{destination_name}@example.invalid", role="user")
        destination.set_password("fictional-e2e-password")
        db.session.add_all([source, destination]); db.session.commit()
        source_id, destination_id = source.id, destination.id
    planned_id = _planned(e2e_app, source_id)
    try:
        client = e2e_app.test_client()
        source_auth = _login(client, source_name, "fictional-e2e-password", "a2000000-0000-4000-8000-000000000201")
        fit_content = (FIXTURE_ROOT / "valid_activity.fit").read_bytes()
        fit_job = _upload(client, source_auth, content=fit_content, filename="synthetic-strong.fit",
            key="e2e-fit-upload", planned_workout_id=planned_id, route_policy="drop")
        assert fit_job.status_code == 201, fit_job.get_json()
        fit_activity = _apply(client, source_auth, fit_job.get_json()["data"]["import_id"], "e2e-fit-apply")
        assert fit_activity.status_code == 201, fit_activity.get_json()
        fit_data = fit_activity.get_json()["data"]["activity"]
        assert fit_data["planLink"]["state"] == "strong_auto_link"
        assert client.get(f"/api/v1/mobile/activities/{fit_data['publicId']}/laps", headers=source_auth).status_code == 200
        assert client.get(f"/api/v1/mobile/activities/{fit_data['publicId']}/series?limit=20", headers=source_auth).status_code == 200
        assert client.get(f"/api/v1/mobile/activities/{fit_data['publicId']}/comparison", headers=source_auth).status_code == 200

        replay = _upload(client, source_auth, content=fit_content, filename="synthetic-renamed.fit",
            key="e2e-fit-repeat", planned_workout_id=planned_id, route_policy="drop")
        assert replay.status_code == 201 and replay.get_json()["data"]["activity_id"] == fit_data["publicId"]
        with e2e_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(Activity).where(Activity.user_id == source_id)) == 1

        gpx_job = _upload(client, source_auth, content=_gpx(segments=2), filename="synthetic-weak.gpx",
            key="e2e-gpx-upload", route_policy="redact", redact_start_meters=10, redact_end_meters=10)
        gpx_activity = _apply(client, source_auth, gpx_job.get_json()["data"]["import_id"], "e2e-gpx-apply")
        assert gpx_activity.status_code == 201, gpx_activity.get_json()
        gpx_data = gpx_activity.get_json()["data"]["activity"]
        candidates = client.get(f"/api/v1/mobile/activities/{gpx_data['publicId']}/plan-candidates", headers=source_auth)
        assert any(row["planned_workout_id"] == planned_id for row in candidates.get_json()["data"]["items"])
        linked = client.post(f"/api/v1/mobile/activities/{gpx_data['publicId']}/plan-link", json={
            "base_revision": gpx_data["revision"], "planned_workout_id": planned_id, "action": "confirm",
        }, headers={**source_auth, "Idempotency-Key": "e2e-gpx-link"})
        assert linked.status_code == 200 and linked.get_json()["data"]["state"] == "user_confirmed"
        assert client.get(f"/api/v1/mobile/activities/{gpx_data['publicId']}/export?format=json", headers=source_auth).status_code == 200
        assert client.get(f"/api/v1/mobile/activities/{gpx_data['publicId']}/export?format=gpx&include_route=true", headers=source_auth).status_code == 200

        sections = ["activities", "activity_laps"]
        default_export = client.post("/api/v1/mobile/portability/exports", json={"sections": sections},
            headers={**source_auth, "Idempotency-Key": "e2e-portable-default"})
        default_package = client.get(f"/api/v1/mobile/portability/exports/{default_export.get_json()['data']['export_id']}/download", headers=source_auth).data
        with ZipFile(io.BytesIO(default_package)) as archive:
            rows = [json.loads(line) for line in archive.read("records/activities.jsonl").splitlines()]
            assert all(row["data"]["route"]["included"] is False for row in rows)

        private_export = client.post("/api/v1/mobile/portability/exports", json={
            "sections": sections, "include_activity_coordinates": True, "include_activity_series": True,
        }, headers={**source_auth, "Idempotency-Key": "e2e-portable-private"})
        package = client.get(f"/api/v1/mobile/portability/exports/{private_export.get_json()['data']['export_id']}/download", headers=source_auth).data
        destination_auth = _login(client, destination_name, "fictional-e2e-password", "a2000000-0000-4000-8000-000000000202")
        inspected = client.post("/api/v1/mobile/portability/imports/inspect", data={
            "file": (io.BytesIO(package), "synthetic-activities.zip"), "sections": json.dumps(sections),
        }, headers=destination_auth, content_type="multipart/form-data")
        assert inspected.status_code == 201, inspected.get_json()
        imported = client.post(f"/api/v1/mobile/portability/imports/{inspected.get_json()['data']['import_id']}/apply",
            json={"confirmed": True, "plan_revision": 1, "decisions": []},
            headers={**destination_auth, "Idempotency-Key": "e2e-portable-apply"})
        assert imported.status_code == 200, imported.get_json()
        assert client.get(f"/api/v1/mobile/activities/{gpx_data['publicId']}", headers=destination_auth).status_code == 404
        with e2e_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(Activity).where(Activity.user_id == destination_id)) == 2
    finally:
        with e2e_app.app_context():
            for account_id in (source_id, destination_id):
                account = db.session.get(User, account_id)
                if account is not None:
                    db.session.delete(account)
            db.session.commit()
        shutil.rmtree(storage_root, ignore_errors=True)
