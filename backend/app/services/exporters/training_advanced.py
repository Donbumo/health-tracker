import csv
import re
from copy import deepcopy
from html import escape
from io import BytesIO, StringIO
from typing import Any
from xml.etree import ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import TrainingPlan, TrainingPlanVersion, TrainingSession
from app.services.exporters.base import ExportArtifact, ExportCapability, ExportError, serialize_json
from app.services.exporters.training_session import (
    TrainingSessionCsvExporter,
    TrainingSessionHtmlExporter,
    TrainingSessionJsonExporter,
    build_completed_workout_document,
)
from app.services.validation import JsonSchemaValidationError, validate_json_document


PERCENT_PATTERNS = (
    re.compile(r"^power_pct_ftp\s*:\s*(0(?:\.\d+)?|1(?:\.0+)?)$", re.I),
    re.compile(r"^(\d+(?:\.\d+)?)\s*%\s*ftp$", re.I),
)
WATTS_PATTERNS = (
    re.compile(r"^power_watts\s*:\s*(\d+(?:\.\d+)?)$", re.I),
    re.compile(r"^(\d+(?:\.\d+)?)\s*w(?:atts?)?$", re.I),
)


def plan_version(resource: TrainingPlan, user_id: int, context: dict[str, Any]) -> TrainingPlanVersion:
    if resource.user_id != user_id:
        raise ExportError("Training plan does not belong to this user")
    version_id = _positive_int(context.get("version_id"))
    if version_id is not None:
        version = next((item for item in resource.versions if item.id == version_id and item.user_id == user_id), None)
    else:
        version = next((item for item in resource.versions if item.version_number == resource.active_version_number and item.user_id == user_id), None)
    if version is None:
        raise ExportError("Training plan version is not available")
    document = deepcopy(version.content)
    document["user_id"] = user_id
    try:
        validate_json_document(document, "training_plan")
    except JsonSchemaValidationError as error:
        raise ExportError("Training plan version is invalid") from error
    return version


def render_plan_json(resource: TrainingPlan, user_id: int, context: dict) -> ExportArtifact:
    version = plan_version(resource, user_id, context)
    document = deepcopy(version.content)
    document["user_id"] = user_id
    validate_json_document(document, "training_plan")
    return ExportArtifact(serialize_json(document), "application/json", "json")


def render_plan_csv(resource: TrainingPlan, user_id: int, context: dict) -> ExportArtifact:
    version = plan_version(resource, user_id, context)
    document = deepcopy(version.content)
    document["user_id"] = user_id
    validate_json_document(document, "training_plan")
    fields = (
        "plan_name", "version", "week_number", "week_name", "day_number", "day_name",
        "exercise_order", "exercise_name", "exercise_notes", "set_number", "reps",
        "reps_min", "reps_max", "duration_seconds", "distance_m", "target", "rest_seconds",
    )
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in _plan_rows(document, version.version_number):
        writer.writerow({key: _csv_safe(row.get(key, "")) for key in fields})
    return ExportArtifact(
        output.getvalue().encode("utf-8-sig"),
        "text/csv",
        "csv",
        warning="CSV flattens the plan hierarchy and may lose metadata.",
    )


def render_plan_html(resource: TrainingPlan, user_id: int, context: dict) -> ExportArtifact:
    version = plan_version(resource, user_id, context)
    document = deepcopy(version.content)
    document["user_id"] = user_id
    validate_json_document(document, "training_plan")
    rows = []
    for row in _plan_rows(document, version.version_number):
        rows.append("<tr>" + "".join(f"<td>{escape(str(row.get(key, '')))}</td>" for key in ("week_number", "day_name", "exercise_name", "set_number", "reps", "reps_min", "reps_max", "duration_seconds", "target", "rest_seconds")) + "</tr>")
    html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(document['data']['name'])}</title>
<style>body{{font-family:system-ui;color:#172033;margin:2rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #94a3b8;padding:.4rem;text-align:left}}@media print{{.no-print{{display:none}}}}</style></head>
<body><button class="no-print" onclick="window.print()">Imprimir</button><h1>{escape(document['data']['name'])}</h1>
<p>Versión {version.version_number}</p><table><thead><tr><th>Semana</th><th>Día</th><th>Ejercicio</th><th>Serie</th><th>Reps</th><th>Min</th><th>Max</th><th>Duración s</th><th>Objetivo</th><th>Descanso s</th></tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    return ExportArtifact(html.encode("utf-8"), "text/html", "html", inline=False)


def render_plan_pdf(resource: TrainingPlan, user_id: int, context: dict) -> ExportArtifact:
    version = plan_version(resource, user_id, context)
    document = deepcopy(version.content)
    document["user_id"] = user_id
    validate_json_document(document, "training_plan")
    rows = [["Semana", "Día", "Ejercicio", "Serie", "Objetivo", "Descanso"]]
    for row in _plan_rows(document, version.version_number):
        target = row.get("target") or row.get("reps") or (
            f"{row.get('reps_min')}-{row.get('reps_max')}" if row.get("reps_min") else row.get("duration_seconds", "")
        )
        rows.append([row.get("week_number", ""), row.get("day_name", ""), row.get("exercise_name", ""), row.get("set_number", ""), target, row.get("rest_seconds", "")])
    content = _pdf_bytes(document["data"]["name"], f"Versión {version.version_number}", rows)
    return ExportArtifact(content, "application/pdf", "pdf")


def render_plan_zwo(resource: TrainingPlan, user_id: int, context: dict) -> ExportArtifact:
    version, day, intervals = _structured_intervals(resource, user_id, context, "percent")
    root = ET.Element("workout_file")
    ET.SubElement(root, "author").text = "Health Tracker"
    ET.SubElement(root, "name").text = f"{resource.name} v{version.version_number} - {day['name']}"
    ET.SubElement(root, "description").text = "Exported from canonical training plan"
    workout = ET.SubElement(root, "workout")
    for interval in intervals:
        tag = "SteadyState"
        name = interval["exercise_name"].casefold()
        if "warm" in name or "calent" in name:
            tag = "Warmup"
        elif "cool" in name or "enfri" in name:
            tag = "Cooldown"
        attributes = {"Duration": str(interval["duration_seconds"]), "Power": _format(interval["target"])}
        if tag in {"Warmup", "Cooldown"}:
            attributes = {"Duration": str(interval["duration_seconds"]), "PowerLow": _format(interval["target"]), "PowerHigh": _format(interval["target"])}
        ET.SubElement(workout, tag, attributes)
    content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.fromstring(content)
    return ExportArtifact(content, "application/vnd.zwift.workout+xml", "zwo", warning="Only duration and FTP-relative power are represented.")


def render_plan_erg(resource: TrainingPlan, user_id: int, context: dict) -> ExportArtifact:
    version, day, intervals = _structured_intervals(resource, user_id, context, "watts")
    lines = ["[COURSE HEADER]", f"VERSION = 2", f"UNITS = ENGLISH", f"DESCRIPTION = {resource.name} v{version.version_number} - {day['name']}", "[END COURSE HEADER]", "[COURSE DATA]"]
    elapsed = 0.0
    lines.append(f"{elapsed:.3f}\t{intervals[0]['target']:.1f}")
    for interval in intervals:
        elapsed += interval["duration_seconds"] / 60
        lines.append(f"{elapsed:.3f}\t{interval['target']:.1f}")
    lines.append("[END COURSE DATA]")
    return ExportArtifact(("\r\n".join(lines) + "\r\n").encode("utf-8"), "application/x-erg", "erg", warning="Only duration and absolute power are represented.")


def render_plan_mrc(resource: TrainingPlan, user_id: int, context: dict) -> ExportArtifact:
    version, day, intervals = _structured_intervals(resource, user_id, context, "percent")
    lines = ["[COURSE HEADER]", "VERSION = 2", "UNITS = ENGLISH", f"DESCRIPTION = {resource.name} v{version.version_number} - {day['name']}", "[END COURSE HEADER]", "[COURSE DATA]"]
    elapsed = 0.0
    lines.append(f"{elapsed:.3f}\t{intervals[0]['target'] * 100:.1f}")
    for interval in intervals:
        elapsed += interval["duration_seconds"] / 60
        lines.append(f"{elapsed:.3f}\t{interval['target'] * 100:.1f}")
    lines.append("[END COURSE DATA]")
    return ExportArtifact(("\r\n".join(lines) + "\r\n").encode("utf-8"), "application/x-mrc", "mrc", warning="Only duration and FTP-relative power are represented.")


def render_session_json(resource: TrainingSession, user_id: int, context: dict) -> ExportArtifact:
    return TrainingSessionJsonExporter().export(resource, user_id)


def render_session_csv(resource: TrainingSession, user_id: int, context: dict) -> ExportArtifact:
    return TrainingSessionCsvExporter().export(resource, user_id)


def render_session_html(resource: TrainingSession, user_id: int, context: dict) -> ExportArtifact:
    artifact = TrainingSessionHtmlExporter().export(resource, user_id)
    return ExportArtifact(artifact.content, artifact.mimetype, artifact.extension, artifact.warning, inline=False)


def render_session_pdf(resource: TrainingSession, user_id: int, _context: dict) -> ExportArtifact:
    document = build_completed_workout_document(resource, user_id)
    validate_json_document(document, "completed_workout")
    rows = [["Ejercicio", "Serie", "Peso kg", "Reps", "RIR", "RPE", "Descanso"]]
    for exercise in resource.exercises:
        for item in exercise.sets:
            rows.append([exercise.name, item.set_number, item.weight_kg, item.reps, item.rir if item.rir is not None else "", item.rpe if item.rpe is not None else "", item.rest_seconds if item.rest_seconds is not None else ""])
    subtitle = f"{document['data']['performed_at']} · {resource.training_plan.name} v{resource.training_plan_version.version_number}"
    return ExportArtifact(_pdf_bytes("Sesión realizada", subtitle, rows), "application/pdf", "pdf")


def plan_capability(resource: TrainingPlan, user_id: int, context: dict) -> ExportCapability:
    plan_version(resource, user_id, context)
    return ExportCapability(True)


def structured_capability(mode: str):
    def capability(resource: TrainingPlan, user_id: int, context: dict) -> ExportCapability:
        try:
            _structured_intervals(resource, user_id, context, mode)
        except ExportError as error:
            return ExportCapability(False, str(error))
        return ExportCapability(True, warnings=("Only one compatible training day is exported.",), lossy_fields=("reps", "load", "rest", "notes", "strength exercises"))
    return capability


def session_capability(resource: TrainingSession, user_id: int, _context: dict) -> ExportCapability:
    try:
        document = build_completed_workout_document(resource, user_id)
        validate_json_document(document, "completed_workout")
    except (JsonSchemaValidationError, ValueError) as error:
        return ExportCapability(False, "Training session data is invalid")
    return ExportCapability(True)


def _structured_intervals(resource: TrainingPlan, user_id: int, context: dict, mode: str):
    version = plan_version(resource, user_id, context)
    days = [(week, day) for week in version.content["data"]["weeks"] for day in week["days"]]
    week_number = _positive_int(context.get("week_number"))
    day_number = _positive_int(context.get("day_number"))
    if week_number is not None or day_number is not None:
        days = [(week, day) for week, day in days if (week_number is None or week["week_number"] == week_number) and (day_number is None or day["day_number"] == day_number)]
    if len(days) != 1:
        raise ExportError("Select exactly one week/day for structured workout export")
    week, day = days[0]
    intervals = []
    for exercise in day["exercises"]:
        for planned_set in exercise["sets"]:
            duration = planned_set.get("duration_seconds")
            target = _power_target(planned_set.get("target"), mode)
            if duration is None or target is None:
                label = "FTP-relative power" if mode == "percent" else "absolute watts"
                raise ExportError(f"Every set requires duration_seconds and {label}; strength plans are not compatible")
            intervals.append({"exercise_name": exercise["name"], "duration_seconds": duration, "target": target})
    if not intervals:
        raise ExportError("The selected training day has no exportable intervals")
    return version, day, intervals


def _power_target(value: Any, mode: str) -> float | None:
    text = str(value or "").strip()
    patterns = PERCENT_PATTERNS if mode == "percent" else WATTS_PATTERNS
    for index, pattern in enumerate(patterns):
        match = pattern.fullmatch(text)
        if match:
            number = float(match.group(1))
            if mode == "percent" and index == 1:
                number /= 100
            if number > 0:
                return number
    return None


def _plan_rows(document: dict[str, Any], version_number: int) -> list[dict[str, Any]]:
    rows = []
    for week in document["data"]["weeks"]:
        for day in week["days"]:
            for exercise in day["exercises"]:
                for planned_set in exercise["sets"]:
                    rows.append({
                        "plan_name": document["data"]["name"], "version": version_number,
                        "week_number": week["week_number"], "week_name": week.get("name", ""),
                        "day_number": day["day_number"], "day_name": day["name"],
                        "exercise_order": exercise["exercise_order"], "exercise_name": exercise["name"],
                        "exercise_notes": exercise.get("notes", ""), **planned_set,
                    })
    return rows


def _pdf_bytes(title: str, subtitle: str, rows: list[list[Any]]) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=28, leftMargin=28, topMargin=32, bottomMargin=32, title=title, author="Health Tracker")
    styles = getSampleStyleSheet()
    safe_rows = [[Paragraph(escape(str(cell)), styles["BodyText"]) for cell in row] for row in rows]
    table = Table(safe_rows, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#64748b")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    document.build([Paragraph(escape(title), styles["Title"]), Paragraph(escape(subtitle), styles["Normal"]), Spacer(1, 12), table])
    content = output.getvalue()
    if not content.startswith(b"%PDF"):
        raise ExportError("PDF generator returned invalid content")
    return content


def _csv_safe(value: Any) -> Any:
    return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value


def _positive_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ExportError("Export selection contains an invalid integer") from None
    if parsed < 1:
        raise ExportError("Export selection must be positive")
    return parsed


def _format(value: float) -> str:
    return format(value, ".6g")
