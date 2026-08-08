from __future__ import annotations

from abc import ABC, abstractmethod
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
from typing import Any
import uuid

from flask import current_app, has_app_context
from jsonschema import Draft202012Validator, FormatChecker

from app.services.real_file_imports import (
    MAX_REAL_FILE_BYTES,
    FileTypeDetector,
    RealFileImportError,
    parse_fit,
    parse_gpx,
    parse_tcx,
)


ACTIVITY_FORMAT = "health-tracker-activity-v1"
SERIES_FORMAT = "activity-series-v1"
MAX_ACTIVITY_DURATION_SECONDS = 14 * 24 * 60 * 60
MAX_LAPS = 2_000
MAX_SAMPLES = 100_000
ALLOWED_EXTENSIONS = {".fit", ".gpx", ".tcx", ".json", ".csv"}
PROVENANCE_VALUES = {"source_provided", "derived_exact", "derived_estimate", "unavailable"}


class ActivityParseError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ParsedActivityFile:
    source_format: str
    document: dict[str, Any]
    samples: list[dict[str, Any]]
    route_points: list[dict[str, Any]]
    laps: list[dict[str, Any]]
    events: list[dict[str, Any]]
    warnings: list[str]
    metadata: dict[str, Any]
    content_fingerprint: str


class ActivityFileParser(ABC):
    source_format: str

    @abstractmethod
    def parse(self, content: bytes, *, public_id: str | None = None) -> ParsedActivityFile:
        raise NotImplementedError


class _LegacyAdapter(ActivityFileParser):
    parser = None

    def parse(self, content: bytes, *, public_id: str | None = None) -> ParsedActivityFile:
        try:
            parsed = self.parser(content, user_id=1)
        except (RealFileImportError, ValueError, OverflowError) as error:
            raise ActivityParseError("invalid_activity_file", _sanitized_error(error)) from error
        activities = [item for item in parsed.documents if item.get("record_type") == "activity"]
        routes = [item for item in parsed.documents if item.get("record_type") == "route"]
        if not activities:
            if self.source_format == "gpx" and routes:
                raise ActivityParseError("missing_timestamps", "El GPX contiene una ruta, pero no timestamps para crear una actividad.")
            raise ActivityParseError("no_activity", "El archivo no contiene una actividad importable.")
        if len(activities) > 1:
            warnings = [*parsed.warnings, "El archivo contiene varias sesiones; Alpha 2.0 importa la primera sesión."]
        else:
            warnings = list(parsed.warnings)
        legacy = activities[0]
        data = legacy["data"]
        points = list(data.get("track") or [])
        route = list((routes[0].get("data") or {}).get("points") or []) if routes else [
            point for point in points if point.get("lat") is not None and point.get("lon") is not None
        ]
        return _normalized(
            data,
            source_format=self.source_format,
            public_id=public_id,
            points=points,
            route_points=route,
            warnings=warnings,
            metadata=parsed.metadata,
        )


class FitActivityParser(_LegacyAdapter):
    source_format = "fit"
    parser = staticmethod(parse_fit)


class GpxActivityParser(_LegacyAdapter):
    source_format = "gpx"
    parser = staticmethod(parse_gpx)


class TcxActivityParser(_LegacyAdapter):
    source_format = "tcx"
    parser = staticmethod(parse_tcx)


class JsonActivityParser(ActivityFileParser):
    source_format = "json"

    def parse(self, content: bytes, *, public_id: str | None = None) -> ParsedActivityFile:
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ActivityParseError("invalid_json", "El JSON de actividad no es válido.") from error
        if not isinstance(payload, dict) or payload.get("format") != ACTIVITY_FORMAT:
            raise ActivityParseError("unsupported_json", "El JSON no usa health-tracker-activity-v1.")
        schema_path = _activity_schema_path()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        if errors:
            error = errors[0]
            raise ActivityParseError("invalid_activity_json", "El JSON no cumple health-tracker-activity-v1.") from error
        document = json.loads(json.dumps(payload))
        activity = document["activity"]
        if public_id:
            activity["publicId"] = public_id
        series = document.pop("series", None) or {}
        samples = _validated_samples(series.get("samples") or [])
        route = document.get("route") or {}
        route_points = _validated_route(route.pop("points", []) or [])
        laps = list(document.get("laps") or [])
        events = list(document.get("events") or [])
        fingerprint = _fingerprint(document, samples, route_points)
        return ParsedActivityFile("json", document, samples, route_points, laps, events, list(document.get("warnings") or []), {"imported_contract": ACTIVITY_FORMAT}, fingerprint)


def _activity_schema_path() -> Path:
    if has_app_context():
        configured = Path(current_app.config["SCHEMA_ROOT"]) / "activity_v1.schema.json"
        if configured.is_file():
            return configured
    candidates = (
        Path(__file__).resolve().parents[3] / "schemas" / "activity_v1.schema.json",
        Path(__file__).resolve().parents[2] / "schemas" / "activity_v1.schema.json",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


class CsvActivityParser(ActivityFileParser):
    source_format = "csv"

    def parse(self, content: bytes, *, public_id: str | None = None) -> ParsedActivityFile:
        try:
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except (UnicodeDecodeError, csv.Error) as error:
            raise ActivityParseError("invalid_csv", "El CSV de actividad no es válido.") from error
        if len(rows) != 1 or not reader.fieldnames or "started_at" not in reader.fieldnames or "activity_type" not in reader.fieldnames:
            raise ActivityParseError("unsupported_csv", "Solo se admite el CSV de resumen exportado por Health Tracker.")
        row = rows[0]
        data: dict[str, Any] = {"started_at": row["started_at"], "activity_type": row["activity_type"]}
        for field in ("ended_at", "source_app", "sport_profile"):
            if row.get(field):
                data[field] = row[field]
        integer_fields = ("duration_seconds", "moving_time_seconds", "calories_kcal", "avg_heart_rate_bpm", "max_heart_rate_bpm", "avg_power_watts", "max_power_watts")
        number_fields = ("distance_meters", "avg_cadence_rpm", "max_cadence_rpm", "avg_speed_mps", "max_speed_mps", "elevation_gain_meters", "elevation_loss_meters")
        try:
            for field in integer_fields:
                if row.get(field):
                    data[field] = int(float(row[field]))
            for field in number_fields:
                if row.get(field):
                    data[field] = float(row[field])
        except (TypeError, ValueError, OverflowError) as error:
            raise ActivityParseError("invalid_csv_value", "El CSV contiene una métrica inválida.") from error
        return _normalized(data, source_format="csv", public_id=public_id, points=[], route_points=[], warnings=[], metadata={"rows": 1})


class ActivityParserRegistry:
    def __init__(self) -> None:
        self.detector = FileTypeDetector()
        self.parsers: dict[str, ActivityFileParser] = {
            "fit": FitActivityParser(),
            "gpx": GpxActivityParser(),
            "tcx": TcxActivityParser(),
            "json": JsonActivityParser(),
            "csv": CsvActivityParser(),
        }

    def detect(self, filename: str, content: bytes) -> tuple[str, str | None]:
        if not content:
            raise ActivityParseError("empty_file", "El archivo está vacío.")
        if len(content) > MAX_REAL_FILE_BYTES:
            raise ActivityParseError("file_too_large", "El archivo supera el límite permitido.")
        suffix = Path(filename or "").suffix.casefold()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ActivityParseError("unsupported_extension", "La extensión no está permitida.")
        head = content[:512].lstrip().lower()
        if head.startswith((b"<html", b"<!doctype html", b"<svg", b"pk\x03\x04", b"mz")):
            raise ActivityParseError("unsafe_file", "El contenido corresponde a un tipo de archivo rechazado.")
        detected = self.detector.detect(filename, content)
        detected = "fit" if detected == "fit_activity" else detected
        if detected not in self.parsers:
            raise ActivityParseError("unsupported_format", "El contenido no corresponde a FIT, GPX, TCX, JSON o CSV admitido.")
        expected = {".fit": "fit", ".gpx": "gpx", ".tcx": "tcx", ".json": "json", ".csv": "csv"}[suffix]
        return detected, None if expected == detected else expected

    def parse(self, filename: str, content: bytes, *, public_id: str | None = None) -> ParsedActivityFile:
        detected, extension_mismatch = self.detect(filename, content)
        result = self.parsers[detected].parse(content, public_id=public_id)
        if extension_mismatch:
            return ParsedActivityFile(
                result.source_format,
                result.document,
                result.samples,
                result.route_points,
                result.laps,
                result.events,
                [*result.warnings, f"La extensión indica {extension_mismatch}, pero el contenido se detectó como {detected}."],
                {**result.metadata, "extension_mismatch": True},
                result.content_fingerprint,
            )
        return result


def _normalized(
    data: dict[str, Any], *, source_format: str, public_id: str | None,
    points: list[dict[str, Any]], route_points: list[dict[str, Any]],
    warnings: list[str], metadata: dict[str, Any],
) -> ParsedActivityFile:
    start = _instant(data.get("started_at"), "start time")
    end = _instant(data.get("ended_at"), "end time") if data.get("ended_at") else None
    if end and end < start:
        raise ActivityParseError("invalid_time_range", "El fin de la actividad es anterior al inicio.")
    elapsed = int((end - start).total_seconds()) if end else None
    if elapsed is not None and elapsed > MAX_ACTIVITY_DURATION_SECONDS:
        raise ActivityParseError("duration_limit", "La actividad supera la duración máxima permitida.")
    samples, routes, sample_warnings = _series(points, start)
    if route_points:
        routes = _route_series(route_points, start)
    warnings = [*_sanitize_warnings(warnings), *sample_warnings]
    if len(samples) > MAX_SAMPLES:
        raise ActivityParseError("sample_limit", "La actividad contiene demasiadas muestras.")
    source_kind = "source_provided" if source_format in {"fit", "csv", "json"} else "derived_exact"
    summary: dict[str, Any] = {}
    metric_fields = {
        "duration": ("duration_seconds", "s"),
        "elapsed_time": ("elapsed_time_seconds", "s"),
        "moving_time": ("moving_time_seconds", "s"),
        "distance": ("distance_meters", "m"),
        "calories": ("calories_kcal", "kcal"),
        "ascent": ("elevation_gain_meters", "m"),
        "descent": ("elevation_loss_meters", "m"),
        "speed_average": ("avg_speed_mps", "m/s"),
        "speed_maximum": ("max_speed_mps", "m/s"),
        "heart_rate_average": ("avg_heart_rate_bpm", "bpm"),
        "heart_rate_maximum": ("max_heart_rate_bpm", "bpm"),
        "cadence_average": ("avg_cadence_rpm", "rpm"),
        "cadence_maximum": ("max_cadence_rpm", "rpm"),
        "power_average": ("avg_power_watts", "W"),
        "power_maximum": ("max_power_watts", "W"),
    }
    derived = {"duration_seconds": elapsed, "elapsed_time_seconds": elapsed}
    for name, (field, unit) in metric_fields.items():
        value = data.get(field, derived.get(field))
        if value is None:
            continue
        value = _finite(value, field)
        if value < 0:
            warnings.append(f"Se descartó {field} porque era negativo.")
            continue
        provenance = source_kind if field in data else "derived_exact"
        summary[name] = {"value": value, "unit": unit, "provenance": provenance}
    raw_type = _sanitize_text(data.get("activity_type") or "unknown", 128) or "unknown"
    discipline = _discipline(raw_type, data.get("sport_profile"))
    environment = "indoor" if discipline == "indoor_cycling" else "outdoor" if routes else "unknown"
    source_application = _sanitize_text(data.get("source_app") or source_format, 128)
    source_device = _sanitize_text(" ".join(filter(None, [str(data.get("manufacturer") or ""), str(data.get("product") or "")])), 128) or None
    lap_rows = _laps(data.get("laps") or [], start, source_kind)
    fields = sorted({key for sample in samples for key in sample if key != "t"})
    series_checksum = hashlib.sha256(_canonical({"format": SERIES_FORMAT, "samples": samples})).hexdigest()
    document: dict[str, Any] = {
        "format": ACTIVITY_FORMAT,
        "formatVersion": "1.0",
        "activity": {
            "publicId": public_id or str(uuid.uuid4()),
            "discipline": discipline,
            "originalType": raw_type,
            "startTime": _rfc3339(start),
            "endTime": _rfc3339(end) if end else None,
            "localDate": start.date().isoformat(),
            "environment": environment,
            "status": "ready_to_import",
            "sourceFormat": source_format,
            "sourceApplication": source_application,
            "sourceDevice": source_device,
            "revision": 1,
        },
        "summary": summary,
        "laps": lap_rows,
        "intervals": [],
        "sampleSeries": {"format": SERIES_FORMAT, "sampleCount": len(samples), "fields": fields, "sha256": series_checksum},
        "route": {"present": bool(routes), "pointCount": len(routes), "policy": "keep"},
        "events": [],
        "sourceReference": {"format": source_format, "application": source_application},
        "warnings": warnings,
    }
    document["activity"] = {key: value for key, value in document["activity"].items() if value is not None}
    fingerprint = _fingerprint(document, samples, routes)
    return ParsedActivityFile(source_format, document, samples, routes, lap_rows, [], warnings, metadata, fingerprint)


def _series(points: list[dict[str, Any]], start: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    samples: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    warnings: list[str] = []
    last_t: float | None = None
    for point in points:
        sample: dict[str, Any] = {}
        timestamp = point.get("timestamp")
        if timestamp:
            instant = _instant(timestamp, "sample timestamp")
            relative = (instant - start).total_seconds()
            if relative < -1 or relative > MAX_ACTIVITY_DURATION_SECONDS:
                warnings.append("Se descartó una muestra con timestamp fuera del rango técnico.")
                continue
            sample["t"] = round(relative, 3)
            if last_t is not None and relative < last_t:
                warnings.append("Se detectaron registros fuera de orden.")
            last_t = relative
        for source, target in (
            ("distance_meters", "distance"), ("elevation_meters", "elevation"),
            ("speed_mps", "speed"), ("heart_rate_bpm", "heart_rate"),
            ("cadence_rpm", "cadence"), ("power_watts", "power"),
            ("temperature_c", "temperature"),
        ):
            if point.get(source) is not None:
                value = _finite(point[source], source)
                if target not in {"elevation", "temperature"} and value < 0:
                    warnings.append(f"Se descartó una muestra inválida de {target}.")
                else:
                    sample[target] = value
        if sample:
            samples.append(sample)
        if point.get("lat") is not None and point.get("lon") is not None:
            route = {key: value for key, value in sample.items() if key in {"t", "distance", "elevation"}}
            route.update(lat=_finite(point["lat"], "latitude"), lon=_finite(point["lon"], "longitude"))
            _validate_coordinate(route)
            routes.append(route)
    return samples, routes, list(dict.fromkeys(warnings))


def _route_series(points: list[dict[str, Any]], start: datetime) -> list[dict[str, Any]]:
    _samples, routes, _warnings = _series(points, start)
    return routes


def _laps(values: list[Any], start: datetime, provenance: str) -> list[dict[str, Any]]:
    output = []
    for index, raw in enumerate(values[:MAX_LAPS], start=1):
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = {"index": index, "publicId": str(uuid.uuid4()), "provenance": provenance}
        for source, target in (("start_time", "startTime"), ("ended_at", "endTime")):
            if raw.get(source):
                item[target] = _rfc3339(_instant(raw[source], f"lap {source}"))
        for source, target in (("duration_seconds", "durationSeconds"), ("distance_meters", "distanceMeters")):
            if raw.get(source) is not None:
                item[target] = _finite(raw[source], source)
        item["metrics"] = {
            key: value for key, value in raw.items()
            if key not in {"start_time", "ended_at", "duration_seconds", "distance_meters"}
            and isinstance(value, (str, int, float, bool, type(None)))
        }
        output.append(item)
    return output


def _validated_samples(values: list[Any]) -> list[dict[str, Any]]:
    if len(values) > MAX_SAMPLES:
        raise ActivityParseError("sample_limit", "La actividad contiene demasiadas muestras.")
    output = []
    allowed = {"t", "distance", "elevation", "speed", "heart_rate", "cadence", "power", "temperature"}
    for raw in values:
        if not isinstance(raw, dict) or not set(raw) <= allowed:
            raise ActivityParseError("invalid_series", "La serie contiene una muestra inválida.")
        item = {key: _finite(value, key) for key, value in raw.items()}
        output.append(item)
    return output


def _validated_route(values: list[Any]) -> list[dict[str, Any]]:
    output = []
    for raw in values:
        if not isinstance(raw, dict) or "lat" not in raw or "lon" not in raw:
            raise ActivityParseError("invalid_route", "La ruta contiene un punto inválido.")
        item = {key: _finite(value, key) for key, value in raw.items() if key in {"t", "lat", "lon", "distance", "elevation"}}
        _validate_coordinate(item)
        output.append(item)
    return output


def _validate_coordinate(point: dict[str, Any]) -> None:
    if not -90 <= point["lat"] <= 90 or not -180 <= point["lon"] <= 180:
        raise ActivityParseError("invalid_coordinate", "La ruta contiene coordenadas fuera de rango.")


def _instant(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as error:
        raise ActivityParseError("invalid_timestamp", f"El {label} no es válido.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        parsed = parsed.astimezone(timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise ActivityParseError("invalid_timestamp", f"El {label} no es válido.") from error
    if not 1970 <= parsed.year <= 2200:
        raise ActivityParseError("invalid_timestamp", f"El {label} está fuera del rango permitido.")
    return parsed


def _finite(value: Any, label: str) -> float | int:
    if isinstance(value, bool):
        raise ActivityParseError("invalid_metric", f"La métrica {label} no es válida.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ActivityParseError("invalid_metric", f"La métrica {label} no es válida.") from error
    if not math.isfinite(number):
        raise ActivityParseError("invalid_metric", f"La métrica {label} no es finita.")
    return int(number) if number.is_integer() else number


def _discipline(activity_type: Any, sport_profile: Any) -> str:
    value = f"{activity_type or ''} {sport_profile or ''}".casefold()
    conservative = (
        ("indoor_cycling", ("indoor cycling", "indoor_cycling", "spinning")),
        ("cycling", ("cycling", "biking", "bike", "ciclismo")),
        ("running", ("running", "run", "carrera")),
        ("walking", ("walking", "walk", "caminata")),
        ("hiking", ("hiking", "hike", "senderismo")),
        ("strength", ("strength", "weight training", "fuerza")),
    )
    for discipline, aliases in conservative:
        if any(re.search(rf"(?:^|[^a-z]){re.escape(alias)}(?:$|[^a-z])", value) for alias in aliases):
            return discipline
    return "unknown" if not value.strip() or value.strip() in {"activity", "outdoor", "unknown"} else "other"


def _sanitize_text(value: Any, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()[:limit]


def _sanitize_warnings(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(_sanitize_text(value, 300) for value in values if _sanitize_text(value, 300)))[:100]


def _sanitized_error(error: Exception) -> str:
    text = _sanitize_text(error, 200)
    return text or "El archivo de actividad no es válido."


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(document: dict[str, Any], samples: list[dict[str, Any]], route: list[dict[str, Any]]) -> str:
    activity = {key: value for key, value in document["activity"].items() if key not in {"publicId", "revision", "status"}}
    evidence = {
        "activity": activity,
        "summary": document.get("summary") or {},
        "laps": [{key: value for key, value in lap.items() if key != "publicId"} for lap in document.get("laps") or []],
        "samples": samples,
        "route": route,
    }
    return hashlib.sha256(_canonical(evidence)).hexdigest()
