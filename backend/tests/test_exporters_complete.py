import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import pytest

from app.extensions import db
from app.models import Activity, ExportRecord, Route, TrainingPlan, TrainingPlanVersion, TrainingSession, User
from app.services.export_artifacts import ExportArtifactService, ExportStorageError
from app.services.exporters import ExporterRegistry
from app.services.exporters.base import ExportError
from app.services.exporters.user_data import build_user_data_document
from app.services.real_file_imports import parse_gpx, parse_tcx
from app.services.training_plans import serialize_training_plan
from app.services.validation import validate_json_document
from tests.conftest import login
from tests.test_phase_6 import _setup_plan_and_session


def _activity_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "activity",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "activity_type": "cycling",
            "started_at": "2026-07-12T10:00:00+00:00",
            "ended_at": "2026-07-12T10:02:00+00:00",
            "duration_seconds": 120,
            "moving_time_seconds": 120,
            "distance_meters": 152.9,
            "calories_kcal": 25,
            "avg_heart_rate_bpm": 132,
            "max_heart_rate_bpm": 145,
            "avg_cadence_rpm": 82,
            "max_cadence_rpm": 90,
            "avg_power_watts": 175,
            "max_power_watts": 210,
            "laps": [
                {"start_time": "2026-07-12T10:00:00+00:00", "ended_at": "2026-07-12T10:01:00+00:00", "duration_seconds": 60},
                {"start_time": "2026-07-12T10:01:00+00:00", "ended_at": "2026-07-12T10:02:00+00:00", "duration_seconds": 60},
            ],
            "track": [
                {"timestamp": "2026-07-12T10:00:00+00:00", "lat": 19.4300, "lon": -99.1300, "elevation_meters": 2240, "heart_rate_bpm": 125, "cadence_rpm": 78, "power_watts": 160, "speed_mps": 2.0, "distance_meters": 0},
                {"timestamp": "2026-07-12T10:01:00+00:00", "lat": 19.4305, "lon": -99.1295, "elevation_meters": 2242, "heart_rate_bpm": 132, "cadence_rpm": 82, "power_watts": 175, "speed_mps": 2.1, "distance_meters": 120},
                {"timestamp": "2026-07-12T10:02:00+00:00", "lat": 19.4310, "lon": -99.1290, "elevation_meters": 2241, "heart_rate_bpm": 145, "cadence_rpm": 90, "power_watts": 210, "speed_mps": 2.2, "distance_meters": 152.9},
            ],
            "bounds": {"min_lat": 19.43, "max_lat": 19.431, "min_lon": -99.13, "max_lon": -99.129},
            "source_app": "qa_fixture",
        },
    }


def _route_document(user_id: int) -> dict:
    points = [
        {key: value for key, value in point.items() if key in {"timestamp", "lat", "lon", "elevation_meters", "distance_meters"}}
        for point in _activity_document(user_id)["data"]["track"]
    ]
    return {
        "schema_version": "1.0",
        "record_type": "route",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": "Ruta QA",
            "route_type": "cycling",
            "distance_meters": 152.9,
            "elevation_gain_meters": 2,
            "elevation_loss_meters": 1,
            "points": points,
            "bounds": {"min_lat": 19.43, "max_lat": 19.431, "min_lon": -99.13, "max_lon": -99.129},
            "source_app": "qa_fixture",
        },
    }


def _add_activity_route(user_id: int) -> tuple[Activity, Route]:
    activity_doc = _activity_document(user_id)
    route_doc = _route_document(user_id)
    validate_json_document(activity_doc, "activity")
    validate_json_document(route_doc, "route")
    activity = Activity(
        user_id=user_id,
        activity_type="cycling",
        started_at=datetime(2026, 7, 12, 10, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 12, 10, 2, tzinfo=timezone.utc),
        duration_seconds=120,
        moving_time_seconds=120,
        distance_meters=152.9,
        calories_kcal=25,
        avg_heart_rate_bpm=132,
        max_heart_rate_bpm=145,
        avg_cadence_rpm=82,
        max_cadence_rpm=90,
        avg_power_watts=175,
        max_power_watts=210,
        source_type="uploaded",
        fingerprint_sha256=hashlib.sha256(b"export-activity").hexdigest(),
        canonical_json=activity_doc,
        laps_json=activity_doc["data"]["laps"],
        track_json=activity_doc["data"]["track"],
        bounds_json=activity_doc["data"]["bounds"],
        point_count=3,
    )
    route = Route(
        user_id=user_id,
        name="Ruta QA",
        route_type="cycling",
        distance_meters=152.9,
        elevation_gain_meters=2,
        elevation_loss_meters=1,
        bounds_json=route_doc["data"]["bounds"],
        points_json=route_doc["data"]["points"],
        point_count=3,
        source_type="uploaded",
        fingerprint_sha256=hashlib.sha256(b"export-route").hexdigest(),
        canonical_json=route_doc,
    )
    db.session.add_all([activity, route])
    db.session.commit()
    return activity, route


def _cycling_plan(user_id: int, *, watts: bool = False) -> TrainingPlan:
    target = "power_watts:190" if watts else "75% FTP"
    document = {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {"name": "Cycling QA watts" if watts else "Cycling QA percent", "weeks": [{"week_number": 1, "days": [{"day_number": 1, "name": "Bike intervals", "exercises": [{"exercise_order": 1, "name": "Warmup", "sets": [{"set_number": 1, "duration_seconds": 300, "target": target}]}, {"exercise_order": 2, "name": "Main interval", "sets": [{"set_number": 1, "duration_seconds": 600, "target": target}]}]}]}]},
    }
    validate_json_document(document, "training_plan")
    plan = TrainingPlan(user_id=user_id, name=document["data"]["name"], active_version_number=1)
    db.session.add(plan)
    db.session.flush()
    version = TrainingPlanVersion(user_id=user_id, training_plan_id=plan.id, version_number=1, created_by_user_id=user_id, schema_version="1.0", sha256=hashlib.sha256(serialize_training_plan(document)).hexdigest(), content=document)
    db.session.add(version)
    db.session.commit()
    return plan


def test_registry_declares_complete_capabilities_and_honest_fit(app, user):
    with app.app_context():
        activity, route = _add_activity_route(user)
        registry = ExporterRegistry()
        assert {spec.format_name for spec in registry.formats_for("activity")} == {"json", "csv", "csv_track", "csv_laps", "gpx", "tcx", "fit"}
        assert {spec.format_name for spec in registry.formats_for("route")} == {"json", "csv", "gpx", "tcx", "fit"}
        assert {spec.format_name for spec in registry.formats_for("training_plan")} == {"json", "csv", "html", "pdf", "zwo", "erg", "mrc", "fit"}
        assert {spec.format_name for spec in registry.formats_for("training_session")} == {"json", "csv", "html", "pdf"}
        assert registry.get("activity", "fit").capability(activity, user, {}).supported is False
        assert registry.get("route", "fit").capability(route, user, {}).supported is False
        with pytest.raises(ExportError):
            registry.get("activity", "xlsx")


def test_activity_and_route_exports_round_trip_semantically(app, user):
    with app.app_context():
        activity, route = _add_activity_route(user)
        registry = ExporterRegistry()
        activity_gpx = registry.get("activity", "gpx").render(activity, user, {}).content
        activity_tcx = registry.get("activity", "tcx").render(activity, user, {}).content
        route_gpx = registry.get("route", "gpx").render(route, user, {}).content
        route_tcx = registry.get("route", "tcx").render(route, user, {}).content
        for content in (activity_gpx, activity_tcx, route_gpx, route_tcx):
            ET.fromstring(content)

        gpx_activity = parse_gpx(activity_gpx, user_id=user).documents[0]["data"]
        tcx_activity = parse_tcx(activity_tcx, user_id=user).documents[0]["data"]
        gpx_route = parse_gpx(route_gpx, user_id=user).documents[0]["data"]
        tcx_route = parse_tcx(route_tcx, user_id=user).documents[0]["data"]

        assert gpx_activity["activity_type"] == "cycling"
        assert len(gpx_activity["laps"]) == 2
        assert len(tcx_activity["laps"]) == 2
        for restored in (gpx_activity, tcx_activity):
            assert len(restored["track"]) == 3
            assert restored["duration_seconds"] == 120
            assert restored["track"][1]["heart_rate_bpm"] == 132
            assert restored["track"][1]["cadence_rpm"] == pytest.approx(82)
            assert restored["track"][1]["power_watts"] == 175
            assert restored["distance_meters"] == pytest.approx(152.9, rel=0.15)
        for restored in (gpx_route, tcx_route):
            assert restored["name"] == "Ruta QA"
            assert len(restored["points"]) == 3
            assert restored["points"][1]["lat"] == pytest.approx(19.4305)


def test_csv_exports_escape_spreadsheet_formulas(app, user):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        activity.activity_type = "=HYPERLINK(\"bad\")"
        activity.canonical_json["data"]["activity_type"] = activity.activity_type
        artifact = ExporterRegistry().get("activity", "csv").render(activity, user, {})
        row = next(csv.DictReader(io.StringIO(artifact.content.decode("utf-8-sig"))))
        assert row["activity_type"].startswith("'=")


def test_training_plan_advanced_formats_and_session_pdf(app, client, user):
    plan_id, session_id = _setup_plan_and_session(app, client, user)
    with app.app_context():
        strength = db.session.get(TrainingPlan, plan_id)
        percent = _cycling_plan(user)
        watts = _cycling_plan(user, watts=True)
        session = db.session.get(TrainingSession, session_id)
        registry = ExporterRegistry()

        assert registry.get("training_plan", "zwo").capability(strength, user, {}).supported is False
        assert registry.get("training_plan", "erg").capability(strength, user, {}).supported is False
        zwo = registry.get("training_plan", "zwo").render(percent, user, {})
        mrc = registry.get("training_plan", "mrc").render(percent, user, {})
        erg = registry.get("training_plan", "erg").render(watts, user, {})
        ET.fromstring(zwo.content)
        assert b"[COURSE DATA]" in mrc.content
        assert b"[COURSE DATA]" in erg.content
        assert b"75.0" in mrc.content
        assert b"190.0" in erg.content

        plan_pdf = registry.get("training_plan", "pdf").render(strength, user, {})
        session_pdf = registry.get("training_session", "pdf").render(session, user, {})
        assert plan_pdf.content.startswith(b"%PDF") and b"/Type /Page" in plan_pdf.content
        assert session_pdf.content.startswith(b"%PDF") and b"/Type /Page" in session_pdf.content


def test_training_plan_historical_version_selection_and_html_escape(app, client, user):
    plan_id, _session_id = _setup_plan_and_session(app, client, user)
    with app.app_context():
        plan = db.session.get(TrainingPlan, plan_id)
        historical = plan.versions[0]
        updated = json.loads(json.dumps(historical.content))
        updated["data"]["name"] = "<script>alert('x')</script>"
        version = TrainingPlanVersion(
            user_id=user,
            training_plan_id=plan.id,
            version_number=2,
            created_by_user_id=user,
            schema_version="1.0",
            sha256=hashlib.sha256(serialize_training_plan(updated)).hexdigest(),
            content=updated,
        )
        plan.active_version_number = 2
        db.session.add(version)
        db.session.commit()
        registry = ExporterRegistry()
        old_json = json.loads(
            registry.get("training_plan", "json").render(
                plan, user, {"version_id": str(historical.id)}
            ).content
        )
        active_json = json.loads(
            registry.get("training_plan", "json").render(plan, user, {}).content
        )
        html = registry.get("training_plan", "html").render(plan, user, {}).content
        assert old_json["data"]["name"] == "Fictional Foundation Plan"
        assert active_json["data"]["name"] == "<script>alert('x')</script>"
        assert b"<script>alert" not in html
        assert b"&lt;script&gt;" in html


def test_export_storage_is_atomic_audited_owner_only_and_tamper_checked(app, user):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        spec = ExporterRegistry().get("activity", "json")
        service = ExportArtifactService()
        assert db.session.execute(db.select(db.func.count(ExportRecord.id))).scalar_one() == 0
        preview = service.preview(spec, activity, user_id=user)
        assert preview.capability.supported is True
        assert db.session.execute(db.select(db.func.count(ExportRecord.id))).scalar_one() == 0
        record = service.generate(spec, activity, user_id=user, source_type="activity", source_id=activity.id)
        path = service.resolve_download(record, user_id=user)
        assert path.read_bytes().startswith(b"{")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record.sha256
        assert not record.relative_path.startswith(("/", "C:"))

        second = User(username="export-owner-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        with pytest.raises(ExportStorageError):
            service.resolve_download(record, user_id=second.id)

        path.write_bytes(b"tampered")
        with pytest.raises(ExportStorageError, match="checksum|size"):
            service.resolve_download(record, user_id=user)


def test_repeated_export_is_explicit_and_expiration_is_controlled(app, user):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        service = ExportArtifactService()
        spec = ExporterRegistry().get("activity", "json")
        first = service.generate(spec, activity, user_id=user, source_type="activity", source_id=activity.id)
        second = service.generate(spec, activity, user_id=user, source_type="activity", source_id=activity.id)
        assert first.id != second.id
        assert first.relative_path != second.relative_path
        assert first.sha256 == second.sha256
        first.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
        with pytest.raises(ExportStorageError, match="expired"):
            service.resolve_download(first, user_id=user)
        assert first.status == "expired"
        assert service.resolve_download(second, user_id=user).is_file()


def test_export_storage_cleans_file_if_database_commit_fails(app, user, monkeypatch):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        service = ExportArtifactService()
        spec = ExporterRegistry().get("activity", "json")
        session = db.session()

        def fail_commit():
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            service.generate(
                spec,
                activity,
                user_id=user,
                source_type="activity",
                source_id=activity.id,
            )
        directory = app.config["GENERATED_UPLOAD_ROOT"] / "exports" / f"user_{user}"
        assert list(directory.iterdir()) == []


def test_export_web_preview_confirm_download_delete_and_isolation(app, client, user):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        activity_id = activity.id
        second = User(username="export-web-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    assert client.get("/exports").status_code == 302
    login(client)
    preview = client.get(f"/exports/new/activity/{activity_id}")
    assert preview.status_code == 200
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(ExportRecord.id))).scalar_one() == 0
    generated = client.post(f"/exports/new/activity/{activity_id}", data={"format": "gpx"})
    assert generated.status_code == 302
    with app.app_context():
        record = db.session.execute(db.select(ExportRecord)).scalar_one()
        record_id = record.id
        assert record.user_id == user
    download = client.get(f"/exports/{record_id}/download")
    assert download.status_code == 200
    assert download.mimetype == "application/gpx+xml"
    assert download.headers["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in download.headers["Content-Disposition"]
    download.close()

    client.post("/logout")
    login(client, "export-web-second", "second-password")
    assert client.get(f"/exports/{record_id}").status_code == 404
    assert client.get(f"/exports/{record_id}/download").status_code == 404
    assert client.get(f"/exports/new/activity/{activity_id}").status_code == 404
    with app.app_context():
        assert db.session.execute(
            db.select(db.func.count(ExportRecord.id)).where(ExportRecord.user_id == second_id)
        ).scalar_one() == 0

    client.post("/logout")
    login(client)
    deleted = client.post(f"/exports/{record_id}/delete")
    assert deleted.status_code == 302
    assert client.get(f"/exports/{record_id}/download").status_code == 404
    with app.app_context():
        assert db.session.get(ExportRecord, record_id).status == "deleted"


def test_export_confirmation_is_csrf_protected_when_enabled(app, client, user):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        activity_id = activity.id
    login(client)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            f"/exports/new/activity/{activity_id}",
            data={"format": "json"},
        )
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert response.status_code == 400
    with app.app_context():
        assert db.session.execute(db.select(db.func.count(ExportRecord.id))).scalar_one() == 0


def test_missing_export_file_returns_not_found_without_exposing_path(app, client, user):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        record = ExportArtifactService().generate(
            ExporterRegistry().get("activity", "json"),
            activity,
            user_id=user,
            source_type="activity",
            source_id=activity.id,
        )
        record_id = record.id
        path = app.config["DATA_ROOT"] / record.relative_path
        path.unlink()
    login(client)
    response = client.get(f"/exports/{record_id}/download")
    assert response.status_code == 404
    assert str(app.config["DATA_ROOT"]).encode() not in response.data


def test_account_export_contains_allowlisted_export_metadata_without_binary_path(app, user):
    with app.app_context():
        activity, _route = _add_activity_route(user)
        spec = ExporterRegistry().get("activity", "json")
        ExportArtifactService().generate(spec, activity, user_id=user, source_type="activity", source_id=activity.id)
        document = build_user_data_document(db.session.get(User, user), user)
        metadata = document["data"]["export_records"][0]
        assert metadata["binary_included"] is False
        assert "relative_path" not in metadata
        assert "stored_filename" not in metadata
        assert "password_hash" not in json.dumps(document)
        validate_json_document(document, "user_data_export")
