import io
import json
import re
import runpy
from pathlib import Path
from html import unescape

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Activity, DailyEnergy, ImportRun, Route, UploadedFile, User, WeighIn
from app.services.account_restore import AccountRestoreService
from app.services.exporters.user_data import build_user_data_document
from app.services.files import store_uploaded_file
from app.services.real_file_imports import (
    FileTypeDetector,
    ParserRegistry,
    RealFileImportError,
    RealFileImportService,
)
from app.services.validation import validate_json_document
from tests.conftest import login


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "qa" / "real-file-imports"


def _hidden(response, name: str) -> str:
    match = re.search(
        rb'name="' + name.encode() + rb'"\s+type="hidden"\s+value="([^"]*)"',
        response.data,
    )
    if match is None:
        match = re.search(
            rb'type="hidden"\s+[^>]*name="' + name.encode() + rb'"[^>]*value="([^"]*)"',
            response.data,
        )
    assert match is not None, response.data.decode("utf-8", errors="replace")
    return unescape(match.group(1).decode("utf-8"))


def _store(content: bytes, user_id: int, filename: str, content_type: str = "application/octet-stream"):
    return store_uploaded_file(
        FileStorage(stream=io.BytesIO(content), filename=filename, content_type=content_type),
        user_id,
    )[0]


def _fixture(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def _gpx_activity() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="QA">
  <trk><name>Ruta ficticia</name><trkseg>
    <trkpt lat="19.4326" lon="-99.1332"><ele>2240</ele><time>2026-07-10T12:00:00Z</time></trkpt>
    <trkpt lat="19.4330" lon="-99.1340"><ele>2248</ele><time>2026-07-10T12:05:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""


def _gpx_route_only() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="QA">
  <rte><name>Ruta sin tiempo</name>
    <rtept lat="19.4300" lon="-99.1300"><ele>2240</ele></rtept>
    <rtept lat="19.4400" lon="-99.1400"><ele>2250</ele></rtept>
  </rte>
</gpx>"""


def _tcx_activity() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport="Biking"><Lap StartTime="2026-07-11T10:00:00Z">
    <Track>
      <Trackpoint><Time>2026-07-11T10:00:00Z</Time><Position><LatitudeDegrees>19.43</LatitudeDegrees><LongitudeDegrees>-99.13</LongitudeDegrees></Position><AltitudeMeters>2240</AltitudeMeters><DistanceMeters>0</DistanceMeters><HeartRateBpm><Value>120</Value></HeartRateBpm><Cadence>80</Cadence></Trackpoint>
      <Trackpoint><Time>2026-07-11T10:10:00Z</Time><Position><LatitudeDegrees>19.44</LatitudeDegrees><LongitudeDegrees>-99.14</LongitudeDegrees></Position><AltitudeMeters>2255</AltitudeMeters><DistanceMeters>1500</DistanceMeters><HeartRateBpm><Value>130</Value></HeartRateBpm><Cadence>85</Cadence></Trackpoint>
    </Track>
  </Lap></Activity></Activities>
</TrainingCenterDatabase>"""


def test_detector_prefers_content_over_extension():
    detector = FileTypeDetector()

    assert detector.detect("wrong.fit", _gpx_activity()) == "gpx"
    assert detector.detect("wrong.csv", _tcx_activity()) == "tcx"
    assert detector.detect("activity.bin", _fixture("valid_activity.fit")) == "fit_activity"


def test_gpx_activity_preview_confirm_reimport_skip_and_export(app, user):
    with app.app_context():
        service = RealFileImportService()
        source = _store(_gpx_activity(), user, "activity_track.gpx", "application/gpx+xml")
        preview = service.preview_uploaded_file(source, user_id=user)

        assert preview["read_only"] is True
        assert preview["target_type"] == "activity"
        assert preview["plan"]["inserts"] == 1
        assert db.session.execute(db.select(Activity)).scalars().all() == []

        result = service.confirm_uploaded_file(
            source,
            user_id=user,
            confirmation_token=preview["confirmation_token"],
        )["commit_result"]
        assert result["committed"] is True
        activity = db.session.execute(db.select(Activity)).scalar_one()
        assert activity.source_file_id == source.id
        assert activity.point_count == 2
        validate_json_document(activity.canonical_json, "activity")

        duplicate = _store(_gpx_activity(), user, "same-content-different-name.gpx", "application/gpx+xml")
        second_preview = service.preview_uploaded_file(duplicate, user_id=user)
        assert second_preview["plan"]["skips"] == 1
        assert second_preview["plan"]["inserts"] == 0


def test_gpx_route_only_imports_route(app, user):
    with app.app_context():
        source = _store(_gpx_route_only(), user, "route_only.gpx", "application/gpx+xml")
        service = RealFileImportService()
        preview = service.preview_uploaded_file(source, user_id=user)
        assert preview["target_type"] == "route"
        assert "no timestamps" in " ".join(preview["warnings"]).casefold()

        service.confirm_uploaded_file(source, user_id=user, confirmation_token=preview["confirmation_token"])
        route = db.session.execute(db.select(Route)).scalar_one()
        assert route.point_count == 2
        assert route.source_file_id == source.id


def test_tcx_parser_generates_activity(app, user):
    with app.app_context():
        registry = ParserRegistry()
        tcx = registry.parse(filename="activity.tcx", content=_tcx_activity(), user_id=user)

        assert tcx.target_type == "activity"
        assert tcx.documents[0]["data"]["avg_heart_rate_bpm"] == 125


def test_fit_binary_fixture_is_valid(app, user):
    with app.app_context():
        parsed = ParserRegistry().parse(filename="valid_activity.fit", content=_fixture("valid_activity.fit"), user_id=user)

        assert parsed.detected_type == "fit_activity"
        assert parsed.target_type == "activity_route"
        assert [document["record_type"] for document in parsed.documents] == ["activity", "route"]
        for document in parsed.documents:
            validate_json_document(document, document["record_type"])


def test_fit_parser_extracts_session_laps_records_and_device(app, user):
    with app.app_context():
        activity = ParserRegistry().parse(
            filename="valid_activity.fit",
            content=_fixture("valid_activity.fit"),
            user_id=user,
        ).documents[0]
        data = activity["data"]

        assert data["activity_type"] == "cycling"
        assert data["started_at"] == "2026-07-12T08:00:00+00:00"
        assert data["ended_at"] == "2026-07-12T08:30:00+00:00"
        assert data["duration_seconds"] == 1800
        assert data["moving_time_seconds"] == 1800
        assert data["distance_meters"] == 12000
        assert data["calories_kcal"] == 320
        assert data["avg_heart_rate_bpm"] == 132
        assert data["max_heart_rate_bpm"] == 140
        assert data["avg_cadence_rpm"] == 86
        assert data["max_cadence_rpm"] == 92
        assert data["avg_speed_mps"] == 6.7
        assert data["max_speed_mps"] == 7.2
        assert data["avg_power_watts"] == 182
        assert data["max_power_watts"] == 240
        assert data["elevation_gain_meters"] == 15
        assert data["elevation_loss_meters"] == 1
        assert data["manufacturer"] == "garmin"
        assert data["product"] == "hrm1"
        assert len(data["laps"]) == 2
        assert len(data["track"]) == 3


def test_fit_with_gps_creates_activity_and_route(app, user):
    with app.app_context():
        parsed = ParserRegistry().parse(filename="valid_activity.fit", content=_fixture("valid_activity.fit"), user_id=user)
        route = parsed.documents[1]

        assert parsed.target_type == "activity_route"
        assert route["record_type"] == "route"
        assert route["data"]["route_type"] == "cycling"
        assert route["data"]["distance_meters"] == 12000
        assert route["data"]["bounds"]["min_lat"] > 19
        assert len(route["data"]["points"]) == 3


def test_fit_without_gps_creates_activity_only(app, user):
    with app.app_context():
        parsed = ParserRegistry().parse(
            filename="valid_activity_no_gps.fit",
            content=_fixture("valid_activity_no_gps.fit"),
            user_id=user,
        )

        assert parsed.target_type == "activity"
        assert [document["record_type"] for document in parsed.documents] == ["activity"]
        assert "no GPS" in " ".join(parsed.warnings)


def test_fit_semicircles_convert_to_degrees(app, user):
    with app.app_context():
        activity = ParserRegistry().parse(
            filename="valid_activity.fit",
            content=_fixture("valid_activity.fit"),
            user_id=user,
        ).documents[0]
        first = activity["data"]["track"][0]

        assert first["lat"] == pytest.approx(19.4326, abs=0.0001)
        assert first["lon"] == pytest.approx(-99.1332, abs=0.0001)


def test_fit_units_are_normalized(app, user):
    with app.app_context():
        activity = ParserRegistry().parse(
            filename="valid_activity.fit",
            content=_fixture("valid_activity.fit"),
            user_id=user,
        ).documents[0]
        data = activity["data"]

        assert data["track"][1]["distance_meters"] == 6000
        assert data["track"][1]["speed_mps"] == 6.6
        assert data["track"][1]["elevation_meters"] == 2248
        assert data["track"][1]["power_watts"] == 180


def test_fit_unknown_fields_do_not_break_parser(app, user):
    with app.app_context():
        parsed = ParserRegistry().parse(
            filename="valid_activity_unknown_field.fit",
            content=_fixture("valid_activity_unknown_field.fit"),
            user_id=user,
        )
        assert parsed.target_type == "activity_route"
        assert parsed.documents[0]["data"]["track"][0]["heart_rate_bpm"] == 120


def test_fit_truncated_file_is_rejected(app, user):
    with app.app_context():
        with pytest.raises(RealFileImportError, match="truncated|Invalid FIT"):
            ParserRegistry().parse(filename="truncated.fit", content=_fixture("truncated.fit"), user_id=user)


def test_fit_invalid_header_or_crc_is_rejected(app, user):
    with app.app_context():
        registry = ParserRegistry()
        with pytest.raises(RealFileImportError, match="Invalid FIT header"):
            registry.parse(filename="invalid_header.fit", content=_fixture("invalid_header.fit"), user_id=user)
        with pytest.raises(RealFileImportError, match="CRC"):
            registry.parse(filename="invalid_crc.fit", content=_fixture("invalid_crc.fit"), user_id=user)


def test_fit_limits_are_enforced(app, user, monkeypatch):
    import app.services.real_file_imports as real_file_imports

    with app.app_context():
        monkeypatch.setattr(real_file_imports, "MAX_FIT_RECORDS", 1)
        with pytest.raises(RealFileImportError, match="too many records"):
            ParserRegistry().parse(filename="valid_activity.fit", content=_fixture("valid_activity.fit"), user_id=user)


def test_fit_invalid_coordinates_are_rejected(app, user):
    builder = runpy.run_path(str(FIXTURE_ROOT / "generate_fit_fixtures.py"))
    content = builder["valid_activity"](gps=True, invalid_coordinates=True)
    with app.app_context():
        with pytest.raises(RealFileImportError, match="invalid coordinates"):
            ParserRegistry().parse(filename="invalid_coordinates.fit", content=content, user_id=user)


def test_malicious_xml_is_rejected(app, user):
    with app.app_context():
        registry = ParserRegistry()
        with pytest.raises(RealFileImportError, match="DTD"):
            registry.parse(filename="evil.gpx", content=b'<!DOCTYPE foo [<!ENTITY xxe "bad">]><gpx></gpx>', user_id=user)


def test_csv_weigh_in_and_daily_energy_imports(app, user):
    with app.app_context():
        service = RealFileImportService()
        weight = _store("fecha;peso;unidad\n10/07/2026;180;lb\n".encode(), user, "weigh_in_es.csv", "text/csv")
        weight_preview = service.preview_uploaded_file(weight, user_id=user, requested_type="weigh_in_csv")
        service.confirm_uploaded_file(weight, user_id=user, requested_type="weigh_in_csv", confirmation_token=weight_preview["confirmation_token"])
        weigh_in = db.session.execute(db.select(WeighIn)).scalar_one()
        assert round(float(weigh_in.weight_kg), 3) == 81.647

        energy = _store("fecha;calorias_totales;pasos;distancia_km\n2026-07-10;2400;9000;6,5\n".encode(), user, "energy_es_semicolon.csv", "text/csv")
        energy_preview = service.preview_uploaded_file(energy, user_id=user)
        service.confirm_uploaded_file(energy, user_id=user, confirmation_token=energy_preview["confirmation_token"])
        daily_energy = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert daily_energy.steps == 9000
        assert daily_energy.distance_meters == 6500


def test_real_file_web_requires_login_preview_confirm_and_audit(app, client, user):
    assert client.get("/imports/files").status_code == 302
    login(client)
    preview = client.post(
        "/imports/files",
        data={"file": (io.BytesIO(_gpx_activity()), "activity_track.gpx"), "requested_type": ""},
        content_type="multipart/form-data",
    )
    assert preview.status_code == 200
    assert b"Preview del archivo" in preview.data
    assert db.session.execute(db.select(Activity)).scalars().all() == []

    response = client.post(
        "/imports/files",
        data={
            "source_file_id": _hidden(preview, "source_file_id"),
            "requested_type": _hidden(preview, "requested_type"),
            "target_type": _hidden(preview, "target_type"),
            "confirmation_token": _hidden(preview, "confirmation_token"),
        },
    )
    assert response.status_code == 200
    assert b"Resumen final" in response.data
    with app.app_context():
        assert db.session.execute(db.select(Activity)).scalar_one()
        run = db.session.execute(db.select(ImportRun)).scalar_one()
        assert run.target_type == "activity"
        assert run.status == "succeeded"


def test_fit_web_preview_is_read_only(app, client, user):
    login(client)
    preview = client.post(
        "/imports/files",
        data={"file": (io.BytesIO(_fixture("valid_activity.fit")), "valid_activity.fit"), "requested_type": ""},
        content_type="multipart/form-data",
    )

    assert preview.status_code == 200
    assert b"fit_activity" in preview.data
    assert b"activity_route" in preview.data
    with app.app_context():
        assert db.session.execute(db.select(Activity)).scalars().all() == []
        assert db.session.execute(db.select(Route)).scalars().all() == []


def test_fit_web_confirm_persists_and_audits(app, client, user):
    login(client)
    preview = client.post(
        "/imports/files",
        data={"file": (io.BytesIO(_fixture("valid_activity.fit")), "valid_activity.fit"), "requested_type": ""},
        content_type="multipart/form-data",
    )
    response = client.post(
        "/imports/files",
        data={
            "source_file_id": _hidden(preview, "source_file_id"),
            "requested_type": _hidden(preview, "requested_type"),
            "target_type": _hidden(preview, "target_type"),
            "confirmation_token": _hidden(preview, "confirmation_token"),
        },
    )

    assert response.status_code == 200
    assert b"Resumen final" in response.data
    with app.app_context():
        activity = db.session.execute(db.select(Activity)).scalar_one()
        route = db.session.execute(db.select(Route)).scalar_one()
        run = db.session.execute(db.select(ImportRun)).scalar_one()
        assert activity.source_file_id is not None
        assert route.source_file_id == activity.source_file_id
        assert run.target_type == "activity_route"
        assert run.status == "succeeded"


def test_fit_reimport_is_idempotent(app, user):
    with app.app_context():
        service = RealFileImportService()
        first = _store(_fixture("valid_activity.fit"), user, "valid_activity.fit")
        preview = service.preview_uploaded_file(first, user_id=user)
        service.confirm_uploaded_file(first, user_id=user, confirmation_token=preview["confirmation_token"])

        second = _store(_fixture("valid_activity.fit"), user, "renamed.fit")
        second_preview = service.preview_uploaded_file(second, user_id=user)
        assert second_preview["plan"]["skips"] == 2
        assert second_preview["plan"]["inserts"] == 0
        service.confirm_uploaded_file(second, user_id=user, confirmation_token=second_preview["confirmation_token"])
        assert db.session.execute(db.select(db.func.count(Activity.id))).scalar_one() == 1
        assert db.session.execute(db.select(db.func.count(Route.id))).scalar_one() == 1


def test_fit_cross_user_isolation(app, client, user):
    with app.app_context():
        second = User(username="fit-cross-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        service = RealFileImportService()
        own = _store(_fixture("valid_activity.fit"), user, "own.fit")
        own_preview = service.preview_uploaded_file(own, user_id=user)
        service.confirm_uploaded_file(own, user_id=user, confirmation_token=own_preview["confirmation_token"])
        other = _store(_fixture("valid_activity.fit"), second.id, "other.fit")
        other_preview = service.preview_uploaded_file(other, user_id=second.id)
        service.confirm_uploaded_file(other, user_id=second.id, confirmation_token=other_preview["confirmation_token"])
        own_activity = db.session.execute(db.select(Activity.id).where(Activity.user_id == user)).scalar_one()
        other_activity = db.session.execute(db.select(Activity.id).where(Activity.user_id == second.id)).scalar_one()

    login(client)
    assert client.get(f"/activities/{own_activity}").status_code == 200
    assert client.get(f"/activities/{other_activity}").status_code == 404


def test_fit_confirmation_token_tampered_and_reused_are_rejected(app, client, user):
    login(client)
    preview = client.post(
        "/imports/files",
        data={"file": (io.BytesIO(_fixture("valid_activity.fit")), "valid_activity.fit"), "requested_type": ""},
        content_type="multipart/form-data",
    )
    base_data = {
        "source_file_id": _hidden(preview, "source_file_id"),
        "requested_type": _hidden(preview, "requested_type"),
        "target_type": _hidden(preview, "target_type"),
        "confirmation_token": _hidden(preview, "confirmation_token"),
    }
    tampered = dict(base_data)
    tampered["confirmation_token"] += "tampered"
    bad = client.post("/imports/files", data=tampered)
    assert bad.status_code == 200
    assert b"No fue posible confirmar" in bad.data
    first = client.post("/imports/files", data=base_data)
    assert first.status_code == 200
    reused = client.post("/imports/files", data=base_data)
    assert reused.status_code == 200
    assert b"ya fue usado" in reused.data


def test_fit_expired_token_is_rejected(app, user):
    with app.app_context():
        service = RealFileImportService()
        source = _store(_fixture("valid_activity.fit"), user, "valid_activity.fit")
        preview = service.preview_uploaded_file(source, user_id=user)
        with pytest.raises(RealFileImportError, match="expired"):
            service.verify_confirmation_token(
                preview["confirmation_token"],
                user_id=user,
                source_file=source,
                target_type=preview["target_type"],
                plan=preview["plan"],
                max_age=-1,
            )


def test_real_file_web_rejects_cross_user_source_file(app, client, user):
    with app.app_context():
        second = User(username="real-file-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        source = _store(_gpx_activity(), second.id, "other.gpx")
        source_id = source.id
    login(client)
    response = client.post(
        "/imports/files",
        data={
            "source_file_id": str(source_id),
            "requested_type": "",
            "target_type": "activity",
            "confirmation_token": "tampered",
        },
    )
    assert response.status_code == 404


def test_activity_and_route_export_restore_roundtrip(app, user):
    with app.app_context():
        service = RealFileImportService()
        activity_source = _store(_gpx_activity(), user, "activity_track.gpx")
        activity_preview = service.preview_uploaded_file(activity_source, user_id=user)
        service.confirm_uploaded_file(activity_source, user_id=user, confirmation_token=activity_preview["confirmation_token"])
        route_source = _store(_gpx_route_only(), user, "route_only.gpx")
        route_preview = service.preview_uploaded_file(route_source, user_id=user)
        service.confirm_uploaded_file(route_source, user_id=user, confirmation_token=route_preview["confirmation_token"])

        owner = db.session.get(User, user)
        export = build_user_data_document(owner, user)
        assert len(export["data"]["activities"]) == 1
        assert len(export["data"]["routes"]) == 1
        validate_json_document(export, "user_data_export")

        target = User(username="activity-restore-target", role="user")
        target.set_password("target-password")
        db.session.add(target)
        db.session.commit()
        preview = AccountRestoreService().preview(export, user_id=target.id)
        assert preview["plan"]["inserts"] >= 2
        result = AccountRestoreService().commit(export, user_id=target.id, confirmation_token=preview["confirmation_token"])
        assert result["committed"] is True
        assert db.session.execute(db.select(Activity).where(Activity.user_id == target.id)).scalar_one()
        assert db.session.execute(db.select(Route).where(Route.user_id == target.id)).scalar_one()

        repeated_preview = AccountRestoreService().preview(export, user_id=target.id)
        activity_ops = [
            op for op in repeated_preview["plan"]["operations"]
            if op["section"] in {"activities", "routes"}
        ]
        assert {op["operation"] for op in activity_ops} == {"skip"}


def test_fit_activity_route_account_roundtrip(app, user):
    with app.app_context():
        service = RealFileImportService()
        source = _store(_fixture("valid_activity.fit"), user, "valid_activity.fit")
        preview = service.preview_uploaded_file(source, user_id=user)
        service.confirm_uploaded_file(source, user_id=user, confirmation_token=preview["confirmation_token"])
        owner = db.session.get(User, user)
        export = build_user_data_document(owner, user)
        activity_doc = export["data"]["activities"][0]
        route_doc = export["data"]["routes"][0]

        target = User(username="fit-roundtrip-target", role="user")
        target.set_password("target-password")
        db.session.add(target)
        db.session.commit()
        restore_preview = AccountRestoreService().preview(export, user_id=target.id)
        result = AccountRestoreService().commit(export, user_id=target.id, confirmation_token=restore_preview["confirmation_token"])
        assert result["committed"] is True

        restored_export = build_user_data_document(db.session.get(User, target.id), target.id)
        restored_activity = restored_export["data"]["activities"][0]
        restored_route = restored_export["data"]["routes"][0]
        assert restored_activity["data"] == activity_doc["data"]
        assert restored_route["data"] == route_doc["data"]
        assert restored_activity["user_id"] == target.id
        assert restored_route["user_id"] == target.id
        assert db.session.execute(db.select(db.func.count(UploadedFile.id)).where(UploadedFile.user_id == target.id)).scalar_one() == 0


def test_tcx_course_creates_route_end_to_end(app, client, user):
    login(client)
    preview = client.post(
        "/imports/files",
        data={"file": (io.BytesIO(_fixture("course.tcx")), "course.tcx"), "requested_type": ""},
        content_type="multipart/form-data",
    )
    assert preview.status_code == 200
    assert b"route" in preview.data
    response = client.post(
        "/imports/files",
        data={
            "source_file_id": _hidden(preview, "source_file_id"),
            "requested_type": _hidden(preview, "requested_type"),
            "target_type": _hidden(preview, "target_type"),
            "confirmation_token": _hidden(preview, "confirmation_token"),
        },
    )
    assert response.status_code == 200
    with app.app_context():
        route = db.session.execute(db.select(Route)).scalar_one()
        assert route.name == "Curso ficticio QA"
        assert route.point_count == 2
        route_id = route.id
    detail = client.get(f"/routes/{route_id}")
    export = client.get(f"/routes/{route_id}/export.json")
    assert detail.status_code == 200
    assert export.status_code == 200
    duplicate = client.post(
        "/imports/files",
        data={"file": (io.BytesIO(_fixture("course.tcx")), "renamed-course.tcx"), "requested_type": ""},
        content_type="multipart/form-data",
    )
    assert b"Skips" in duplicate.data


def test_activity_pages_and_exports_are_isolated(app, client, user):
    with app.app_context():
        second = User(username="activity-page-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        service = RealFileImportService()
        own_source = _store(_gpx_activity(), user, "own.gpx")
        own_preview = service.preview_uploaded_file(own_source, user_id=user)
        service.confirm_uploaded_file(own_source, user_id=user, confirmation_token=own_preview["confirmation_token"])
        other_source = _store(_gpx_activity(), second.id, "other.gpx")
        other_preview = service.preview_uploaded_file(other_source, user_id=second.id)
        service.confirm_uploaded_file(other_source, user_id=second.id, confirmation_token=other_preview["confirmation_token"])
        own_id = db.session.execute(db.select(Activity.id).where(Activity.user_id == user)).scalar_one()
        other_id = db.session.execute(db.select(Activity.id).where(Activity.user_id == second.id)).scalar_one()

    login(client)
    assert client.get("/activities").status_code == 200
    assert client.get(f"/activities/{own_id}").status_code == 200
    assert client.get(f"/activities/{other_id}").status_code == 404
    export = client.get(f"/activities/{own_id}/export.json")
    assert export.status_code == 200
    assert export.mimetype == "application/json"


def test_real_file_qa_fixtures_parse(app, user):
    fixture_root = Path(__file__).resolve().parents[2] / "examples" / "qa" / "real-file-imports"
    with app.app_context():
        registry = ParserRegistry()
        for filename in (
            "activity_track.gpx",
            "route_only.gpx",
            "activity.tcx",
            "course.tcx",
            "valid_activity.fit",
            "valid_activity_no_gps.fit",
            "valid_activity_unknown_field.fit",
            "weigh_in_es.csv",
            "weigh_in_en_lb.csv",
            "energy_es_semicolon.csv",
        ):
            parsed = registry.parse(filename=filename, content=(fixture_root / filename).read_bytes(), user_id=user)
            assert parsed.documents
        with pytest.raises(RealFileImportError):
            registry.parse(filename="truncated.fit", content=(fixture_root / "truncated.fit").read_bytes(), user_id=user)
        with pytest.raises(RealFileImportError):
            registry.parse(filename="invalid_crc.fit", content=(fixture_root / "invalid_crc.fit").read_bytes(), user_id=user)
        with pytest.raises(RealFileImportError):
            registry.parse(filename="invalid_header.fit", content=(fixture_root / "invalid_header.fit").read_bytes(), user_id=user)
