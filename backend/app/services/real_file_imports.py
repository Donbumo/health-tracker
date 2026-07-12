from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

import fitdecode
from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.models import UploadedFile
from app.services.files import mark_import_status
from app.services.importers.standard_import_executor import (
    StandardImportError,
    StandardImportExecutor,
    canonical_sha256,
)
from app.services.validation import validate_json_document


MAX_REAL_FILE_BYTES = 10 * 1024 * 1024
MAX_XML_NODES = 20000
MAX_POINTS = 10000
MAX_FIT_RECORDS = 10000
REAL_FILE_TOKEN_SALT = "real-file-import-confirmation-v1"


class RealFileImportError(ValueError):
    pass


class RealFileImportTokenError(RealFileImportError):
    pass


@dataclass(frozen=True)
class ParsedRealFile:
    detected_type: str
    target_type: str
    documents: list[dict[str, Any]]
    warnings: list[str]
    metadata: dict[str, Any]


class FileTypeDetector:
    def detect(self, filename: str, content: bytes) -> str:
        suffix = Path(filename or "").suffix.casefold()
        head = content[:256].lstrip()
        if _has_fit_magic(content):
            return "fit_activity"
        if head.startswith(b"<"):
            lower = head.lower()
            if b"<gpx" in lower:
                return "gpx"
            if b"trainingcenterdatabase" in lower or b"<tcx" in lower:
                return "tcx"
        if suffix == ".json":
            return "json"
        if suffix == ".csv" or suffix in {".tsv", ".txt"}:
            return "csv"
        if suffix == ".gpx":
            return "gpx"
        if suffix == ".tcx":
            return "tcx"
        if suffix == ".fit":
            return "fit_activity"
        return "unknown"


class ParserRegistry:
    def __init__(self) -> None:
        self.detector = FileTypeDetector()

    def parse(
        self,
        *,
        filename: str,
        content: bytes,
        user_id: int,
        requested_type: str | None = None,
    ) -> ParsedRealFile:
        detected = self.detector.detect(filename, content)
        if requested_type in {"weigh_in_csv", "daily_energy_csv"}:
            return parse_csv_import(content, user_id=user_id, target=requested_type)
        if detected == "gpx":
            return parse_gpx(content, user_id=user_id)
        if detected == "tcx":
            return parse_tcx(content, user_id=user_id)
        if detected == "fit_activity":
            return parse_fit(content, user_id=user_id)
        if detected == "json":
            payload = json.loads(content.decode("utf-8-sig"))
            target = _json_target(payload)
            validate_json_document(payload, target)
            return ParsedRealFile(target, target, [payload | {"user_id": user_id}], [], {"format": "json"})
        if detected == "csv":
            return parse_csv_import(content, user_id=user_id, target=None)
        raise RealFileImportError("Unsupported file type")


class RealFileImportService:
    def __init__(
        self,
        registry: ParserRegistry | None = None,
        executor: StandardImportExecutor | None = None,
    ) -> None:
        self.registry = registry or ParserRegistry()
        self.executor = executor or StandardImportExecutor()

    def preview_uploaded_file(
        self,
        source_file: UploadedFile,
        *,
        user_id: int,
        requested_type: str | None = None,
    ) -> dict[str, Any]:
        content = _read_uploaded_content(source_file, user_id)
        parsed = self.registry.parse(
            filename=source_file.original_filename,
            content=content,
            user_id=user_id,
            requested_type=requested_type,
        )
        documents = [
            _with_source_file_id(document, source_file.id)
            if parsed.target_type in {"activity", "route", "activity_route"}
            else document
            for document in parsed.documents
        ]
        plan = self.executor.plan_documents(
            documents,
            user_id=user_id,
            target_type=parsed.target_type,
        )
        token = self.build_confirmation_token(
            user_id=user_id,
            source_file=source_file,
            target_type=parsed.target_type,
            plan=plan,
        )
        return {
            "read_only": True,
            "detected_type": parsed.detected_type,
            "target_type": parsed.target_type,
            "documents": documents,
            "warnings": parsed.warnings,
            "metadata": parsed.metadata,
            "plan": plan,
            "confirmation_token": token,
        }

    def build_confirmation_token(
        self,
        *,
        user_id: int,
        source_file: UploadedFile,
        target_type: str,
        plan: dict[str, Any],
    ) -> str:
        return _serializer().dumps(
            {
                "user_id": user_id,
                "source_file_id": source_file.id,
                "file_sha256": source_file.sha256,
                "target_type": target_type,
                "plan_sha256": canonical_sha256(_plan_fingerprint(plan)),
            },
            salt=REAL_FILE_TOKEN_SALT,
        )

    def verify_confirmation_token(
        self,
        token: str,
        *,
        user_id: int,
        source_file: UploadedFile,
        target_type: str,
        plan: dict[str, Any],
        max_age: int = 15 * 60,
    ) -> None:
        try:
            data = _serializer().loads(token, salt=REAL_FILE_TOKEN_SALT, max_age=max_age)
        except SignatureExpired as error:
            raise RealFileImportTokenError("Real file import token expired") from error
        except BadSignature as error:
            raise RealFileImportTokenError("Real file import token is invalid") from error
        expected = {
            "user_id": user_id,
            "source_file_id": source_file.id,
            "file_sha256": source_file.sha256,
            "target_type": target_type,
            "plan_sha256": canonical_sha256(_plan_fingerprint(plan)),
        }
        if any(data.get(key) != value for key, value in expected.items()):
            raise RealFileImportTokenError("Real file import preview changed")

    def confirm_uploaded_file(
        self,
        source_file: UploadedFile,
        *,
        user_id: int,
        confirmation_token: str,
        requested_type: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview_uploaded_file(source_file, user_id=user_id, requested_type=requested_type)
        self.verify_confirmation_token(
            confirmation_token,
            user_id=user_id,
            source_file=source_file,
            target_type=preview["target_type"],
            plan=preview["plan"],
        )
        result = self.executor.commit_documents(
            preview["documents"],
            user_id=user_id,
            target_type=preview["target_type"],
            confirmed=True,
            audit_payload={
                "source_file_id": source_file.id,
                "sha256": source_file.sha256,
                "target_type": preview["target_type"],
            },
            audit_metadata={
                "route": "/imports/files/confirm",
                "mode": "real_file_confirm",
                "detected_type": preview["detected_type"],
                "document_count": len(preview["documents"]),
                "contract_version": "real-file-import-v1",
            },
        )
        mark_import_status(
            source_file,
            user_id,
            status="imported" if result["committed"] else "error",
            detected_type=preview["detected_type"],
            error_message=None if result["committed"] else "; ".join(result.get("errors") or []),
        )
        return {**preview, "commit_result": result}


def parse_csv_import(content: bytes, *, user_id: int, target: str | None) -> ParsedRealFile:
    text = content.decode("utf-8-sig")
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        raise RealFileImportError("CSV has no rows")
    headers = {header.strip().casefold(): header for header in (rows[0].keys() or []) if header}
    resolved = target or _csv_target(headers)
    documents = []
    warnings = []
    for index, row in enumerate(rows, start=1):
        try:
            documents.append(_csv_row_to_document(row, user_id=user_id, target=resolved))
        except RealFileImportError as error:
            warnings.append(f"row {index}: {error}")
    if not documents:
        raise RealFileImportError("CSV generated no valid rows")
    target_type = "weigh_in_batch" if resolved == "weigh_in_csv" else "daily_energy"
    return ParsedRealFile(resolved, target_type, documents, warnings, {"rows": len(rows), "delimiter": dialect.delimiter})


def parse_gpx(content: bytes, *, user_id: int) -> ParsedRealFile:
    root = _safe_xml_root(content)
    points = []
    for element in root.iter():
        if _local_name(element.tag) in {"trkpt", "rtept"}:
            if len(points) >= MAX_POINTS:
                raise RealFileImportError("Too many GPX points")
            points.append(_xml_point(element))
    if not points:
        raise RealFileImportError("GPX contains no route/activity points")
    route_doc = _route_document(user_id, "GPX route", "gpx", points, "gpx")
    timestamps = [point.get("timestamp") for point in points if point.get("timestamp")]
    warnings = []
    if timestamps:
        documents = [_activity_document(user_id, "outdoor", points, "gpx", source_app="gpx")]
        target = "activity"
    else:
        documents = [route_doc]
        target = "route"
        warnings.append("GPX has no timestamps; activity summary was not generated.")
    return ParsedRealFile("gpx", target, documents, warnings, {"points": len(points)})


def parse_tcx(content: bytes, *, user_id: int) -> ParsedRealFile:
    root = _safe_xml_root(content)
    points = []
    laps = []
    has_activity = any(_local_name(element.tag) == "Activity" for element in root.iter())
    course_name = _first_text(root, "Name") if not has_activity else None
    for element in root.iter():
        name = _local_name(element.tag)
        if name == "Lap":
            laps.append({"start_time": element.attrib.get("StartTime")})
        if name == "Trackpoint":
            if len(points) >= MAX_POINTS:
                raise RealFileImportError("Too many TCX points")
            point = _tcx_point(element)
            if point:
                points.append(point)
    if not points:
        raise RealFileImportError("TCX contains no trackpoints")
    if not has_activity:
        route = _route_document(
            user_id,
            course_name or "TCX course",
            "tcx_course",
            points,
            "tcx",
        )
        return ParsedRealFile("tcx", "route", [route], [], {"points": len(points), "course": True})
    activity = _activity_document(user_id, "activity", points, "tcx", source_app="tcx")
    activity["data"]["laps"] = laps[:1000]
    return ParsedRealFile("tcx", "activity", [activity], [], {"points": len(points), "laps": len(laps)})


def parse_fit(content: bytes, *, user_id: int) -> ParsedRealFile:
    if not _has_fit_magic(content):
        raise RealFileImportError("Invalid FIT header")
    try:
        frames = _decode_fit_frames(content)
    except fitdecode.FitHeaderError as error:
        raise RealFileImportError("Invalid FIT header") from error
    except fitdecode.FitCRCError as error:
        raise RealFileImportError("Invalid FIT CRC") from error
    except fitdecode.FitEOFError as error:
        raise RealFileImportError("FIT file is truncated") from error
    except fitdecode.FitError as error:
        raise RealFileImportError("Invalid FIT file") from error

    records = frames["records"]
    if len(records) > MAX_FIT_RECORDS:
        raise RealFileImportError("FIT contains too many records")
    sessions = frames["sessions"] or [_fit_synthetic_session(records)]
    documents: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, session in enumerate(sessions, start=1):
        session_records = _fit_records_for_session(records, session)
        if not session_records:
            session_records = records
        activity = _fit_activity_document(
            user_id,
            session,
            session_records,
            frames["laps"],
            frames["device"],
            frames["sport"],
            session_index=index,
        )
        documents.append(activity)
        activity_warnings = activity["data"].get("warnings") or []
        warnings.extend(activity_warnings)
        gps_points = [
            point
            for point in activity["data"].get("track") or []
            if point.get("lat") is not None and point.get("lon") is not None
        ]
        if len(gps_points) >= 2:
            route = _route_document(
                user_id,
                f"FIT {activity['data']['activity_type']} {activity['data']['started_at']}",
                activity["data"]["activity_type"],
                gps_points,
                "fit",
            )
            documents.append(route)
    if not documents:
        raise RealFileImportError("FIT contains no importable activity sessions")
    for document in documents:
        validate_json_document(document, document["record_type"])
    target = "activity_route" if any(document["record_type"] == "route" for document in documents) else "activity"
    return ParsedRealFile(
        "fit_activity",
        target,
        documents,
        warnings,
        {"fit_decoder": "fitdecode", "sessions": len(sessions), "records": len(records)},
    )


def _decode_fit_frames(content: bytes) -> dict[str, Any]:
    decoded = {
        "records": [],
        "laps": [],
        "sessions": [],
        "device": {},
        "sport": {},
    }
    with fitdecode.FitReader(
        io.BytesIO(content),
        check_crc=fitdecode.CrcCheck.RAISE,
        error_handling=fitdecode.ErrorHandling.RAISE,
    ) as reader:
        for frame in reader:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            fields = _fit_fields(frame)
            if frame.name == "record":
                decoded["records"].append(_fit_record(fields))
            elif frame.name == "lap":
                decoded["laps"].append(_fit_lap(fields))
            elif frame.name == "session":
                decoded["sessions"].append(_fit_session(fields))
            elif frame.name == "device_info":
                decoded["device"].update(_fit_device(fields))
            elif frame.name == "file_id":
                decoded["device"].update({key: value for key, value in _fit_device(fields).items() if value is not None})
            elif frame.name == "sport":
                decoded["sport"].update(
                    {
                        "sport": _text(fields.get("sport")),
                        "sub_sport": _text(fields.get("sub_sport")),
                    }
                )
    return decoded


def _fit_fields(frame) -> dict[str, Any]:
    return {
        field.name: field.value
        for field in frame.fields
        if field.name and field.value is not None
    }


def _fit_record(fields: dict[str, Any]) -> dict[str, Any]:
    point: dict[str, Any] = {}
    if fields.get("timestamp"):
        point["timestamp"] = fields["timestamp"].isoformat()
    lat = _semicircles_to_degrees(fields.get("position_lat"))
    lon = _semicircles_to_degrees(fields.get("position_long"))
    if lat is not None and lon is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise RealFileImportError("FIT contains invalid coordinates")
        point["lat"] = lat
        point["lon"] = lon
    _copy_finite(point, "elevation_meters", fields.get("enhanced_altitude", fields.get("altitude")))
    _copy_int(point, "heart_rate_bpm", fields.get("heart_rate"))
    _copy_finite(point, "cadence_rpm", fields.get("cadence"))
    _copy_int(point, "power_watts", fields.get("power"))
    _copy_finite(point, "speed_mps", fields.get("enhanced_speed", fields.get("speed")))
    _copy_finite(point, "distance_meters", fields.get("distance"))
    return point


def _fit_lap(fields: dict[str, Any]) -> dict[str, Any]:
    lap = {
        "start_time": fields["start_time"].isoformat() if fields.get("start_time") else None,
        "ended_at": fields["timestamp"].isoformat() if fields.get("timestamp") else None,
    }
    for source, target in (
        ("total_elapsed_time", "duration_seconds"),
        ("total_timer_time", "moving_time_seconds"),
        ("total_distance", "distance_meters"),
        ("total_calories", "calories_kcal"),
        ("avg_heart_rate", "avg_heart_rate_bpm"),
        ("max_heart_rate", "max_heart_rate_bpm"),
        ("avg_cadence", "avg_cadence_rpm"),
        ("max_cadence", "max_cadence_rpm"),
        ("enhanced_avg_speed", "avg_speed_mps"),
        ("avg_speed", "avg_speed_mps"),
        ("enhanced_max_speed", "max_speed_mps"),
        ("max_speed", "max_speed_mps"),
        ("avg_power", "avg_power_watts"),
        ("max_power", "max_power_watts"),
        ("total_ascent", "elevation_gain_meters"),
        ("total_descent", "elevation_loss_meters"),
    ):
        if target in lap and source in {"avg_speed", "max_speed"}:
            continue
        _copy_finite(lap, target, fields.get(source))
    return {key: value for key, value in lap.items() if value is not None}


def _fit_session(fields: dict[str, Any]) -> dict[str, Any]:
    session = {
        "started_at": fields.get("start_time"),
        "ended_at": fields.get("timestamp"),
        "sport": _text(fields.get("sport")),
        "sub_sport": _text(fields.get("sub_sport")),
    }
    for source, target in (
        ("total_elapsed_time", "duration_seconds"),
        ("total_timer_time", "moving_time_seconds"),
        ("total_distance", "distance_meters"),
        ("total_calories", "calories_kcal"),
        ("avg_heart_rate", "avg_heart_rate_bpm"),
        ("max_heart_rate", "max_heart_rate_bpm"),
        ("avg_cadence", "avg_cadence_rpm"),
        ("max_cadence", "max_cadence_rpm"),
        ("enhanced_avg_speed", "avg_speed_mps"),
        ("avg_speed", "avg_speed_mps"),
        ("enhanced_max_speed", "max_speed_mps"),
        ("max_speed", "max_speed_mps"),
        ("avg_power", "avg_power_watts"),
        ("max_power", "max_power_watts"),
        ("total_ascent", "elevation_gain_meters"),
        ("total_descent", "elevation_loss_meters"),
    ):
        if target in session and source in {"avg_speed", "max_speed"}:
            continue
        _copy_finite(session, target, fields.get(source))
    return session


def _fit_device(fields: dict[str, Any]) -> dict[str, str | None]:
    product = fields.get("product") or fields.get("garmin_product")
    return {
        "manufacturer": _text(fields.get("manufacturer")),
        "product": _text(product),
    }


def _fit_synthetic_session(records: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [
        datetime.fromisoformat(record["timestamp"])
        for record in records
        if record.get("timestamp")
    ]
    if not timestamps:
        raise RealFileImportError("FIT contains no session or timestamped records")
    return {
        "started_at": min(timestamps),
        "ended_at": max(timestamps),
        "sport": "activity",
    }


def _fit_records_for_session(records: list[dict[str, Any]], session: dict[str, Any]) -> list[dict[str, Any]]:
    start = session.get("started_at")
    end = session.get("ended_at")
    if not start and not end:
        return records
    selected = []
    for record in records:
        if not record.get("timestamp"):
            continue
        timestamp = datetime.fromisoformat(record["timestamp"])
        if start and timestamp < start:
            continue
        if end and timestamp > end:
            continue
        selected.append(record)
    return selected


def _fit_activity_document(
    user_id: int,
    session: dict[str, Any],
    records: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    device: dict[str, Any],
    sport: dict[str, Any],
    *,
    session_index: int,
) -> dict[str, Any]:
    activity_type = _text(session.get("sport") or sport.get("sport"))
    if not activity_type:
        raise RealFileImportError("FIT session is missing sport/activity type")
    started = session.get("started_at")
    if not started:
        timestamps = [datetime.fromisoformat(record["timestamp"]) for record in records if record.get("timestamp")]
        if not timestamps:
            raise RealFileImportError("FIT session is missing start time")
        started = min(timestamps)
    ended = session.get("ended_at")
    if not ended:
        timestamps = [datetime.fromisoformat(record["timestamp"]) for record in records if record.get("timestamp")]
        ended = max(timestamps) if timestamps else None
    data = {
        "activity_type": activity_type,
        "started_at": started.isoformat(),
        "track": records,
        "source_app": "fit",
        "laps": laps[:1000],
    }
    if ended:
        data["ended_at"] = ended.isoformat()
    sub_sport = _text(session.get("sub_sport") or sport.get("sub_sport"))
    if sub_sport:
        data["sport_profile"] = f"{activity_type}/{sub_sport}"
    for field in (
        "duration_seconds",
        "moving_time_seconds",
        "distance_meters",
        "calories_kcal",
        "avg_heart_rate_bpm",
        "max_heart_rate_bpm",
        "avg_cadence_rpm",
        "max_cadence_rpm",
        "avg_speed_mps",
        "max_speed_mps",
        "elevation_gain_meters",
        "elevation_loss_meters",
        "avg_power_watts",
        "max_power_watts",
    ):
        value = session.get(field)
        if value is not None:
            data[field] = int(value) if field.endswith("_bpm") or field.endswith("_watts") or field.endswith("_seconds") else value
    if device.get("manufacturer"):
        data["manufacturer"] = device["manufacturer"]
    if device.get("product"):
        data["product"] = device["product"]
    gps_points = [point for point in records if point.get("lat") is not None and point.get("lon") is not None]
    warnings = []
    if gps_points:
        data["bounds"] = _bounds(gps_points)
        if "distance_meters" not in data:
            data["distance_meters"] = _track_distance(gps_points)
    else:
        warnings.append("FIT activity has no GPS track; route was not generated.")
    if warnings:
        data["warnings"] = warnings
    if len(records) > MAX_POINTS:
        raise RealFileImportError("FIT contains too many trackpoints")
    return {
        "schema_version": "1.0",
        "record_type": "activity",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": data,
    }


def _semicircles_to_degrees(value: Any) -> float | None:
    if value is None:
        return None
    return _finite_float(value) * 180 / (2**31)


def _copy_finite(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    target[key] = _finite_float(value)


def _copy_int(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    parsed = _finite_float(value)
    target[key] = int(parsed)


def _finite_float(value: Any) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RealFileImportError("FIT contains non-finite numeric values")
    return parsed


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _csv_row_to_document(row: dict[str, str], *, user_id: int, target: str) -> dict[str, Any]:
    normalized = {key.strip().casefold(): value.strip() for key, value in row.items() if key}
    if target == "weigh_in_csv":
        recorded = _parse_datetime(_pick(normalized, "recorded_at", "fecha", "fecha_hora", "date", "datetime"))
        weight_value = _parse_number(_pick(normalized, "weight_kg", "peso_kg", "peso", "weight"))
        unit = (_pick(normalized, "unit", "unidad") or "kg").casefold()
        if unit in {"lb", "lbs", "pound", "pounds"}:
            weight_value = weight_value * Decimal("0.45359237")
        data = {"recorded_at": recorded, "weight_kg": float(weight_value), "source": "csv"}
        return {"schema_version": "1.0", "record_type": "weigh_in", "user_id": user_id, "source_type": "uploaded", "data": data}
    record_date = _parse_date(_pick(normalized, "date", "fecha"))
    data = {"date": record_date, "source": "csv"}
    for aliases, canonical, integer in (
        (("total_expenditure_kcal", "calorias_totales", "total_calories"), "total_expenditure_kcal", False),
        (("active_expenditure_kcal", "calorias_activas", "active_calories"), "active_expenditure_kcal", False),
        (("resting_expenditure_kcal", "calorias_reposo", "resting_calories"), "resting_expenditure_kcal", False),
        (("steps", "pasos"), "steps", True),
        (("distance_meters", "distancia_m", "distance_m"), "distance_meters", False),
        (("distance_km", "distancia_km"), "distance_meters", False),
    ):
        value = _maybe_pick(normalized, *aliases)
        if value:
            parsed = _parse_number(value)
            if aliases[0] == "distance_km":
                parsed *= Decimal("1000")
            data[canonical] = int(parsed) if integer else float(parsed)
    return {"schema_version": "1.0", "record_type": "daily_energy", "user_id": user_id, "source_type": "uploaded", "data": data}


def _activity_document(user_id: int, activity_type: str, points: list[dict[str, Any]], source: str, *, source_app: str) -> dict[str, Any]:
    timestamps = [datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00")) for point in points if point.get("timestamp")]
    started = min(timestamps) if timestamps else datetime.now(timezone.utc)
    ended = max(timestamps) if timestamps else None
    distance = _track_distance(points)
    gain, loss = _elevation_gain_loss(points)
    data = {
        "activity_type": activity_type,
        "started_at": started.isoformat(),
        "distance_meters": distance,
        "elevation_gain_meters": gain,
        "elevation_loss_meters": loss,
        "track": points,
        "bounds": _bounds(points),
        "source_app": source_app,
    }
    if ended:
        data["ended_at"] = ended.isoformat()
        data["duration_seconds"] = int((ended - started).total_seconds())
        data["moving_time_seconds"] = data["duration_seconds"]
    hrs = [point["heart_rate_bpm"] for point in points if point.get("heart_rate_bpm")]
    if hrs:
        data["avg_heart_rate_bpm"] = round(sum(hrs) / len(hrs))
        data["max_heart_rate_bpm"] = max(hrs)
    return {"schema_version": "1.0", "record_type": "activity", "user_id": user_id, "source_type": "uploaded", "data": data}


def _route_document(user_id: int, name: str, route_type: str, points: list[dict[str, Any]], source_app: str) -> dict[str, Any]:
    route_points = _route_points(points)
    gain, loss = _elevation_gain_loss(points)
    return {
        "schema_version": "1.0",
        "record_type": "route",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": name,
            "route_type": route_type,
            "distance_meters": _track_distance(points),
            "elevation_gain_meters": gain,
            "elevation_loss_meters": loss,
            "bounds": _bounds(route_points),
            "points": route_points,
            "source_app": source_app,
        },
    }


def _route_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {"timestamp", "lat", "lon", "elevation_meters", "distance_meters"}
    return [
        {key: value for key, value in point.items() if key in allowed}
        for point in points
        if point.get("lat") is not None and point.get("lon") is not None
    ]


def _safe_xml_root(content: bytes) -> ET.Element:
    if b"<!DOCTYPE" in content[:1024].upper() or b"<!ENTITY" in content[:2048].upper():
        raise RealFileImportError("XML DTD/entities are not allowed")
    root = ET.fromstring(content)
    if sum(1 for _ in root.iter()) > MAX_XML_NODES:
        raise RealFileImportError("XML contains too many nodes")
    return root


def _first_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name:
            text = (element.text or "").strip()
            if text:
                return text
    return None


def _xml_point(element: ET.Element) -> dict[str, Any]:
    point = {"lat": float(element.attrib["lat"]), "lon": float(element.attrib["lon"])}
    for child in element:
        name = _local_name(child.tag)
        text = (child.text or "").strip()
        if name == "ele" and text:
            point["elevation_meters"] = float(text)
        if name == "time" and text:
            point["timestamp"] = text.replace("Z", "+00:00")
        if name in {"hr", "heartrate"} and text:
            point["heart_rate_bpm"] = int(float(text))
    return point


def _tcx_point(element: ET.Element) -> dict[str, Any] | None:
    point: dict[str, Any] = {}
    for child in element.iter():
        name = _local_name(child.tag)
        text = (child.text or "").strip()
        if name == "Time" and text:
            point["timestamp"] = text.replace("Z", "+00:00")
        elif name == "LatitudeDegrees" and text:
            point["lat"] = float(text)
        elif name == "LongitudeDegrees" and text:
            point["lon"] = float(text)
        elif name == "AltitudeMeters" and text:
            point["elevation_meters"] = float(text)
        elif name == "DistanceMeters" and text:
            point["distance_meters"] = float(text)
        elif name == "Value" and text and "heart_rate_bpm" not in point:
            point["heart_rate_bpm"] = int(float(text))
        elif name in {"Cadence", "RunCadence"} and text:
            point["cadence_rpm"] = float(text)
        elif name in {"Watts", "Power"} and text:
            point["power_watts"] = int(float(text))
        elif name == "Speed" and text:
            point["speed_mps"] = float(text)
    return point if {"lat", "lon"} <= point.keys() else None


def _read_uploaded_content(source_file: UploadedFile, user_id: int) -> bytes:
    if source_file.user_id != user_id:
        raise RealFileImportError("File does not belong to this user")
    path = Path(current_app.config["DATA_ROOT"]) / source_file.storage_path
    content = path.read_bytes()
    if len(content) > MAX_REAL_FILE_BYTES:
        raise RealFileImportError("File is too large")
    if hashlib.sha256(content).hexdigest() != source_file.sha256:
        raise RealFileImportError("File checksum does not match metadata")
    return content


def _has_fit_magic(content: bytes) -> bool:
    return len(content) >= 12 and content[8:12] == b".FIT"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _plan_fingerprint(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: plan.get(key) for key in ("total", "valid", "invalid", "inserts", "updates", "skips", "conflicts", "operations")}


def _json_target(payload: dict[str, Any]) -> str:
    if payload.get("type") == "medical_lab":
        return "medical_lab"
    if payload.get("record_type") == "training_plan":
        return "training_plan"
    if payload.get("record_type") == "completed_workout":
        return "completed_workout"
    raise RealFileImportError("Unsupported JSON file for real-file pipeline")


def _csv_target(headers: dict[str, str]) -> str:
    keys = set(headers)
    if keys & {"peso", "peso_kg", "weight", "weight_kg"}:
        return "weigh_in_csv"
    if keys & {"steps", "pasos", "calorias_totales", "total_expenditure_kcal"}:
        return "daily_energy_csv"
    raise RealFileImportError("Could not detect CSV profile")


def _pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name.casefold())
        if value:
            return value
    raise RealFileImportError(f"Missing required column: {names[0]}")


def _maybe_pick(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name.casefold())
        if value:
            return value
    return None


def _with_source_file_id(document: dict[str, Any], source_file_id: int) -> dict[str, Any]:
    copied = json.loads(json.dumps(document, ensure_ascii=False))
    copied["source_file_id"] = source_file_id
    return copied


def _parse_number(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))


def _parse_date(value: str) -> str:
    value = value.strip()
    if "/" in value:
        day, month, year = value.split("/")
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return value[:10]


def _parse_datetime(value: str) -> str:
    value = value.strip()
    if "T" in value and ("+" in value or value.endswith("Z")):
        return value.replace("Z", "+00:00")
    if "/" in value:
        parts = value.split(maxsplit=1)
        date_part = parts[0]
        time_part = parts[1] if len(parts) > 1 else "00:00"
        day, month, year = date_part.split("/")
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}T{time_part}:00+00:00"
    if " " in value:
        return value.replace(" ", "T") + ":00+00:00"
    return value + "T00:00:00+00:00"


def _track_distance(points: list[dict[str, Any]]) -> float:
    explicit = [point.get("distance_meters") for point in points if point.get("distance_meters") is not None]
    if explicit:
        return float(max(explicit))
    total = 0.0
    for first, second in zip(points, points[1:]):
        total += _haversine(first["lat"], first["lon"], second["lat"], second["lon"])
    return round(total, 2)


def _elevation_gain_loss(points: list[dict[str, Any]]) -> tuple[float, float]:
    gain = loss = 0.0
    elevations = [point.get("elevation_meters") for point in points if point.get("elevation_meters") is not None]
    for first, second in zip(elevations, elevations[1:]):
        delta = second - first
        if delta > 0:
            gain += delta
        else:
            loss += abs(delta)
    return round(gain, 2), round(loss, 2)


def _bounds(points: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "min_lat": min(point["lat"] for point in points),
        "max_lat": max(point["lat"] for point in points),
        "min_lon": min(point["lon"] for point in points),
        "max_lon": max(point["lon"] for point in points),
    }


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
