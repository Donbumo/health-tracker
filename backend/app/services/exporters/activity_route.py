import csv
import json
from copy import deepcopy
from io import StringIO
from typing import Any
from xml.etree import ElementTree as ET

from app.models import Activity, Route
from app.services.exporters.base import ExportArtifact, ExportCapability, ExportError, serialize_json
from app.services.validation import JsonSchemaValidationError, validate_json_document


GPX_NS = "http://www.topografix.com/GPX/1/1"
GPXTPX_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
HT_NS = "https://health-tracker.local/xml/extensions/1"
TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
TPX_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"

ET.register_namespace("gpx", GPX_NS)
ET.register_namespace("gpxtpx", GPXTPX_NS)
ET.register_namespace("ht", HT_NS)
ET.register_namespace("tcx", TCX_NS)
ET.register_namespace("tpx", TPX_NS)


def activity_document(activity: Activity, user_id: int) -> dict[str, Any]:
    _ensure_owner(activity, user_id)
    document = deepcopy(activity.canonical_json)
    document["user_id"] = user_id
    if activity.source_file_id:
        document["source_file_id"] = activity.source_file_id
    try:
        validate_json_document(document, "activity")
    except JsonSchemaValidationError as error:
        raise ExportError("Activity canonical data is invalid") from error
    return document


def route_document(route: Route, user_id: int) -> dict[str, Any]:
    _ensure_owner(route, user_id)
    document = deepcopy(route.canonical_json)
    document["user_id"] = user_id
    if route.source_file_id:
        document["source_file_id"] = route.source_file_id
    try:
        validate_json_document(document, "route")
    except JsonSchemaValidationError as error:
        raise ExportError("Route canonical data is invalid") from error
    return document


def render_activity_json(resource: Activity, user_id: int, _context: dict) -> ExportArtifact:
    return ExportArtifact(serialize_json(activity_document(resource, user_id)), "application/json", "json")


def render_route_json(resource: Route, user_id: int, _context: dict) -> ExportArtifact:
    return ExportArtifact(serialize_json(route_document(resource, user_id)), "application/json", "json")


def render_activity_summary_csv(resource: Activity, user_id: int, _context: dict) -> ExportArtifact:
    document = activity_document(resource, user_id)
    data = document["data"]
    fields = (
        "activity_type", "started_at", "ended_at", "duration_seconds",
        "moving_time_seconds", "distance_meters", "calories_kcal",
        "avg_heart_rate_bpm", "max_heart_rate_bpm", "avg_cadence_rpm",
        "max_cadence_rpm", "avg_speed_mps", "max_speed_mps",
        "elevation_gain_meters", "elevation_loss_meters", "avg_power_watts",
        "max_power_watts", "sport_profile", "manufacturer", "product", "source_app",
    )
    return _csv_artifact(fields, [{field: data.get(field, "") for field in fields}], "csv")


def render_activity_track_csv(resource: Activity, user_id: int, _context: dict) -> ExportArtifact:
    points = activity_document(resource, user_id)["data"].get("track") or []
    fields = (
        "index", "timestamp", "lat", "lon", "elevation_meters",
        "heart_rate_bpm", "cadence_rpm", "power_watts", "speed_mps", "distance_meters",
    )
    rows = [{"index": index, **{field: point.get(field, "") for field in fields if field != "index"}} for index, point in enumerate(points, 1)]
    return _csv_artifact(fields, rows, "csv")


def render_activity_laps_csv(resource: Activity, user_id: int, _context: dict) -> ExportArtifact:
    laps = activity_document(resource, user_id)["data"].get("laps") or []
    keys = sorted({key for lap in laps for key in lap})
    fields = tuple(["lap_number", *keys])
    rows = [{"lap_number": index, **{key: lap.get(key, "") for key in keys}} for index, lap in enumerate(laps, 1)]
    return _csv_artifact(fields, rows, "csv")


def render_route_points_csv(resource: Route, user_id: int, _context: dict) -> ExportArtifact:
    points = route_document(resource, user_id)["data"].get("points") or []
    fields = ("index", "timestamp", "lat", "lon", "elevation_meters", "distance_meters")
    rows = [{"index": index, **{field: point.get(field, "") for field in fields if field != "index"}} for index, point in enumerate(points, 1)]
    return _csv_artifact(fields, rows, "csv")


def render_activity_gpx(resource: Activity, user_id: int, _context: dict) -> ExportArtifact:
    data = activity_document(resource, user_id)["data"]
    points = _coordinate_points(data.get("track"))
    if not points:
        raise ExportError("Activity has no GPS points")
    root = ET.Element(_tag(GPX_NS, "gpx"), {"version": "1.1", "creator": "Health Tracker"})
    metadata = ET.SubElement(root, _tag(GPX_NS, "metadata"))
    metadata_extensions = ET.SubElement(metadata, _tag(GPX_NS, "extensions"))
    ET.SubElement(metadata_extensions, _tag(HT_NS, "activity_type")).text = _safe_xml_text(data.get("activity_type"), 64)
    if data.get("laps"):
        ET.SubElement(metadata_extensions, _tag(HT_NS, "laps")).text = json.dumps(data["laps"], ensure_ascii=False, separators=(",", ":"))
    track = ET.SubElement(root, _tag(GPX_NS, "trk"))
    ET.SubElement(track, _tag(GPX_NS, "name")).text = _safe_xml_text(data.get("activity_type"), 128)
    segment = ET.SubElement(track, _tag(GPX_NS, "trkseg"))
    for point in points:
        element = ET.SubElement(segment, _tag(GPX_NS, "trkpt"), _coordinates(point))
        _append_gpx_point(element, point)
    return _xml_artifact(root, "gpx", "application/gpx+xml")


def render_route_gpx(resource: Route, user_id: int, _context: dict) -> ExportArtifact:
    data = route_document(resource, user_id)["data"]
    points = _coordinate_points(data.get("points"))
    if not points:
        raise ExportError("Route has no GPS points")
    root = ET.Element(_tag(GPX_NS, "gpx"), {"version": "1.1", "creator": "Health Tracker"})
    route = ET.SubElement(root, _tag(GPX_NS, "rte"))
    ET.SubElement(route, _tag(GPX_NS, "name")).text = _safe_xml_text(data.get("name"), 255)
    for point in points:
        element = ET.SubElement(route, _tag(GPX_NS, "rtept"), _coordinates(point))
        _append_gpx_point(element, point)
    return _xml_artifact(root, "gpx", "application/gpx+xml")


def render_activity_tcx(resource: Activity, user_id: int, _context: dict) -> ExportArtifact:
    data = activity_document(resource, user_id)["data"]
    points = _coordinate_points(data.get("track"))
    if not points:
        raise ExportError("Activity has no GPS points")
    root = ET.Element(_tag(TCX_NS, "TrainingCenterDatabase"))
    activities = ET.SubElement(root, _tag(TCX_NS, "Activities"))
    activity = ET.SubElement(activities, _tag(TCX_NS, "Activity"), {"Sport": _tcx_sport(data.get("activity_type"))})
    ET.SubElement(activity, _tag(TCX_NS, "Id")).text = data["started_at"]
    laps = data.get("laps") or [{}]
    for index, lap_data in enumerate(laps):
        lap = ET.SubElement(activity, _tag(TCX_NS, "Lap"), {"StartTime": str(lap_data.get("start_time") or data["started_at"])})
        _append_tcx_summary(lap, lap_data or data)
        track = ET.SubElement(lap, _tag(TCX_NS, "Track"))
        for point in _points_for_lap(points, lap_data, index, len(laps)):
            _append_tcx_trackpoint(track, point)
    return _xml_artifact(root, "tcx", "application/vnd.garmin.tcx+xml")


def render_route_tcx(resource: Route, user_id: int, _context: dict) -> ExportArtifact:
    data = route_document(resource, user_id)["data"]
    points = _coordinate_points(data.get("points"))
    if not points:
        raise ExportError("Route has no GPS points")
    root = ET.Element(_tag(TCX_NS, "TrainingCenterDatabase"))
    courses = ET.SubElement(root, _tag(TCX_NS, "Courses"))
    course = ET.SubElement(courses, _tag(TCX_NS, "Course"))
    ET.SubElement(course, _tag(TCX_NS, "Name")).text = _safe_xml_text(data["name"], 255)
    if data.get("distance_meters") is not None:
        ET.SubElement(course, _tag(TCX_NS, "DistanceMeters")).text = _number(data["distance_meters"])
    track = ET.SubElement(course, _tag(TCX_NS, "Track"))
    for point in points:
        _append_tcx_trackpoint(track, point)
    return _xml_artifact(root, "tcx", "application/vnd.garmin.tcx+xml")


def always_capability(resource: Any, user_id: int, _context: dict) -> ExportCapability:
    if isinstance(resource, Activity):
        activity_document(resource, user_id)
    elif isinstance(resource, Route):
        route_document(resource, user_id)
    else:
        _ensure_owner(resource, user_id)
    return ExportCapability(True)


def activity_track_capability(resource: Activity, user_id: int, _context: dict) -> ExportCapability:
    activity_document(resource, user_id)
    if not (resource.track_json or []):
        return ExportCapability(False, "Activity has no trackpoints")
    return ExportCapability(True)


def activity_laps_capability(resource: Activity, user_id: int, _context: dict) -> ExportCapability:
    activity_document(resource, user_id)
    if not (resource.laps_json or []):
        return ExportCapability(False, "Activity has no laps")
    return ExportCapability(True)


def gps_capability(resource: Activity | Route, user_id: int, _context: dict) -> ExportCapability:
    if isinstance(resource, Activity):
        activity_document(resource, user_id)
    else:
        route_document(resource, user_id)
    points = resource.track_json if isinstance(resource, Activity) else resource.points_json
    if not _coordinate_points(points):
        return ExportCapability(False, "GPS coordinates are required for this format")
    return ExportCapability(True, lossy_fields=("device metadata", "non-standard warnings"))


def unsupported_fit_capability(resource: Any, user_id: int, _context: dict) -> ExportCapability:
    _ensure_owner(resource, user_id)
    return ExportCapability(False, "FIT output is experimental and unsupported: no maintained encoder is configured")


def _csv_artifact(fields: tuple[str, ...], rows: list[dict[str, Any]], extension: str) -> ExportArtifact:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key, "")) for key in fields})
    return ExportArtifact(output.getvalue().encode("utf-8-sig"), "text/csv", extension)


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _append_gpx_point(element: ET.Element, point: dict[str, Any]) -> None:
    if point.get("elevation_meters") is not None:
        ET.SubElement(element, _tag(GPX_NS, "ele")).text = _number(point["elevation_meters"])
    if point.get("timestamp"):
        ET.SubElement(element, _tag(GPX_NS, "time")).text = str(point["timestamp"])
    metrics = {key: point.get(key) for key in ("heart_rate_bpm", "cadence_rpm", "power_watts", "speed_mps", "distance_meters") if point.get(key) is not None}
    if metrics:
        extensions = ET.SubElement(element, _tag(GPX_NS, "extensions"))
        tpx = ET.SubElement(extensions, _tag(GPXTPX_NS, "TrackPointExtension"))
        if "heart_rate_bpm" in metrics:
            ET.SubElement(tpx, _tag(GPXTPX_NS, "hr")).text = _number(metrics["heart_rate_bpm"])
        if "cadence_rpm" in metrics:
            ET.SubElement(tpx, _tag(GPXTPX_NS, "cad")).text = _number(metrics["cadence_rpm"])
        for field, xml_name in (("power_watts", "power"), ("speed_mps", "speed"), ("distance_meters", "distance")):
            if field in metrics:
                ET.SubElement(extensions, _tag(HT_NS, xml_name)).text = _number(metrics[field])


def _append_tcx_summary(lap: ET.Element, data: dict[str, Any]) -> None:
    for key, xml_name in (("duration_seconds", "TotalTimeSeconds"), ("distance_meters", "DistanceMeters"), ("calories_kcal", "Calories")):
        if data.get(key) is not None:
            ET.SubElement(lap, _tag(TCX_NS, xml_name)).text = _number(data[key])


def _append_tcx_trackpoint(track: ET.Element, point: dict[str, Any]) -> None:
    element = ET.SubElement(track, _tag(TCX_NS, "Trackpoint"))
    if point.get("timestamp"):
        ET.SubElement(element, _tag(TCX_NS, "Time")).text = str(point["timestamp"])
    position = ET.SubElement(element, _tag(TCX_NS, "Position"))
    ET.SubElement(position, _tag(TCX_NS, "LatitudeDegrees")).text = _number(point["lat"])
    ET.SubElement(position, _tag(TCX_NS, "LongitudeDegrees")).text = _number(point["lon"])
    if point.get("elevation_meters") is not None:
        ET.SubElement(element, _tag(TCX_NS, "AltitudeMeters")).text = _number(point["elevation_meters"])
    if point.get("distance_meters") is not None:
        ET.SubElement(element, _tag(TCX_NS, "DistanceMeters")).text = _number(point["distance_meters"])
    if point.get("heart_rate_bpm") is not None:
        hr = ET.SubElement(element, _tag(TCX_NS, "HeartRateBpm"))
        ET.SubElement(hr, _tag(TCX_NS, "Value")).text = _number(point["heart_rate_bpm"])
    if point.get("cadence_rpm") is not None:
        ET.SubElement(element, _tag(TCX_NS, "Cadence")).text = _number(point["cadence_rpm"])
    if point.get("speed_mps") is not None or point.get("power_watts") is not None:
        extensions = ET.SubElement(element, _tag(TCX_NS, "Extensions"))
        tpx = ET.SubElement(extensions, _tag(TPX_NS, "TPX"))
        if point.get("speed_mps") is not None:
            ET.SubElement(tpx, _tag(TPX_NS, "Speed")).text = _number(point["speed_mps"])
        if point.get("power_watts") is not None:
            ET.SubElement(tpx, _tag(TPX_NS, "Watts")).text = _number(point["power_watts"])


def _coordinate_points(points: Any) -> list[dict[str, Any]]:
    return [point for point in (points or []) if point.get("lat") is not None and point.get("lon") is not None]


def _points_for_lap(points: list[dict[str, Any]], lap: dict[str, Any], index: int, total: int) -> list[dict[str, Any]]:
    start = lap.get("start_time")
    end = lap.get("ended_at")
    if start or end:
        selected = [
            point
            for point in points
            if point.get("timestamp")
            and (not start or point["timestamp"] >= start)
            and (
                not end
                or point["timestamp"] < end
                or (index == total - 1 and point["timestamp"] == end)
            )
        ]
        if selected:
            return selected
    if total == 1:
        return points
    start_index = len(points) * index // total
    end_index = len(points) * (index + 1) // total
    return points[start_index:end_index]


def _coordinates(point: dict[str, Any]) -> dict[str, str]:
    return {"lat": _number(point["lat"]), "lon": _number(point["lon"])}


def _xml_artifact(root: ET.Element, extension: str, media_type: str) -> ExportArtifact:
    content = ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
    ET.fromstring(content)
    return ExportArtifact(content, media_type, extension)


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _safe_xml_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _number(value: Any) -> str:
    return format(float(value), ".12g")


def _tcx_sport(value: Any) -> str:
    normalized = str(value or "Other").casefold()
    if "bike" in normalized or "cycl" in normalized:
        return "Biking"
    if "run" in normalized:
        return "Running"
    return "Other"


def _ensure_owner(resource: Any, user_id: int) -> None:
    if resource.user_id != user_id:
        raise ExportError("Resource does not belong to this user")
