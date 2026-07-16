import csv
from html import escape
from io import StringIO
from zoneinfo import ZoneInfo

from flask import current_app

from app.models import TrainingSession
from app.services.exporters.base import BaseExporter, ExportArtifact, serialize_json
from app.services.validation import validate_json_document


CSV_WARNING = (
    "CSV aplana ejercicios y series; no conserva toda la estructura del JSON interno."
)


def build_completed_workout_document(
    session: TrainingSession,
    user_id: int,
) -> dict:
    if session.user_id != user_id:
        raise ValueError("Training session does not belong to this user")
    if (
        session.training_plan.user_id != user_id
        or session.training_plan_version.user_id != user_id
    ):
        raise ValueError("Training session associations do not belong to this user")

    performed_at = session.performed_at
    if performed_at.tzinfo is None or performed_at.utcoffset() is None:
        performed_at = performed_at.replace(
            tzinfo=ZoneInfo(current_app.config["APP_TIMEZONE"])
        )

    exercises = []
    for exercise in session.exercises:
        exercise_data = {
            "exercise_order": exercise.exercise_order,
            "planned_exercise_order": exercise.planned_exercise_order,
            "name": exercise.name,
            "sets": [],
        }
        if exercise.notes:
            exercise_data["notes"] = exercise.notes
        for training_set in exercise.sets:
            set_data = {
                "set_number": training_set.set_number,
                "planned_set_number": training_set.planned_set_number,
                "weight_kg": float(training_set.weight_kg),
                "reps": training_set.reps,
            }
            if training_set.rir is not None:
                set_data["rir"] = float(training_set.rir)
            if training_set.rpe is not None:
                set_data["rpe"] = float(training_set.rpe)
            if training_set.rest_seconds is not None:
                set_data["rest_seconds"] = training_set.rest_seconds
            if training_set.notes:
                set_data["notes"] = training_set.notes
            if training_set.load_details_json:
                set_data["load_details"] = training_set.load_details_json
            exercise_data["sets"].append(set_data)
        exercises.append(exercise_data)

    data = {
        "training_plan_id": session.training_plan_id,
        "training_plan_version_id": session.training_plan_version_id,
        "performed_at": performed_at.isoformat(timespec="seconds"),
        "planned_week_number": session.planned_week_number,
        "planned_day_number": session.planned_day_number,
        "exercises": exercises,
    }
    if session.notes:
        data["notes"] = session.notes
    if session.duration_seconds is not None:
        data["duration_seconds"] = session.duration_seconds
    if session.average_heart_rate_bpm is not None:
        data["average_heart_rate_bpm"] = session.average_heart_rate_bpm
    if session.calories_burned is not None:
        data["calories_burned"] = float(session.calories_burned)
    if session.client_submission_id is not None:
        data["client_submission_id"] = session.client_submission_id

    source_type = (
        session.source_file.source_type
        if session.source_file
        and session.source_file.source_type
        in {"manual_generated", "uploaded", "device_sync"}
        else "uploaded"
    )
    return {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": user_id,
        "source_type": source_type,
        "data": data,
    }


class TrainingSessionJsonExporter(BaseExporter):
    format_name = "json"

    def export(self, resource: TrainingSession, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        document = build_completed_workout_document(resource, user_id)
        validate_json_document(document, "completed_workout")
        return ExportArtifact(
            content=serialize_json(document),
            mimetype="application/json",
            extension="json",
        )


class TrainingSessionCsvExporter(BaseExporter):
    format_name = "csv"
    fieldnames = (
        "session_id",
        "performed_at",
        "plan_name",
        "plan_version",
        "planned_week",
        "planned_day",
        "duration_seconds",
        "average_heart_rate_bpm",
        "calories_burned",
        "exercise_order",
        "exercise_name",
        "set_number",
        "planned_set_number",
        "weight_kg",
        "load_mode",
        "load_unit",
        "load_components",
        "reps",
        "rir",
        "rpe",
        "rest_seconds",
        "session_notes",
        "exercise_notes",
        "set_notes",
    )

    def export(self, resource: TrainingSession, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        document = build_completed_workout_document(resource, user_id)
        validate_json_document(document, "completed_workout")

        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=self.fieldnames)
        writer.writeheader()
        for exercise in resource.exercises:
            for training_set in exercise.sets:
                writer.writerow(
                    {
                        "session_id": resource.id,
                        "performed_at": document["data"]["performed_at"],
                        "plan_name": resource.training_plan.name,
                        "plan_version": resource.training_plan_version.version_number,
                        "planned_week": resource.planned_week_number,
                        "planned_day": resource.planned_day_number,
                        "duration_seconds": resource.duration_seconds or "",
                        "average_heart_rate_bpm": (
                            resource.average_heart_rate_bpm or ""
                        ),
                        "calories_burned": (
                            resource.calories_burned
                            if resource.calories_burned is not None
                            else ""
                        ),
                        "exercise_order": exercise.exercise_order,
                        "exercise_name": exercise.name,
                        "set_number": training_set.set_number,
                        "planned_set_number": training_set.planned_set_number,
                        "weight_kg": training_set.weight_kg,
                        "load_mode": (training_set.load_details_json or {}).get("load_mode", ""),
                        "load_unit": (training_set.load_details_json or {}).get("original_unit", ""),
                        "load_components": str((training_set.load_details_json or {}).get("components", "")),
                        "reps": training_set.reps,
                        "rir": training_set.rir if training_set.rir is not None else "",
                        "rpe": training_set.rpe if training_set.rpe is not None else "",
                        "rest_seconds": (
                            training_set.rest_seconds
                            if training_set.rest_seconds is not None
                            else ""
                        ),
                        "session_notes": resource.notes or "",
                        "exercise_notes": exercise.notes or "",
                        "set_notes": training_set.notes or "",
                    }
                )

        return ExportArtifact(
            content=output.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            extension="csv",
            warning=CSV_WARNING,
        )


class TrainingSessionHtmlExporter(BaseExporter):
    format_name = "html"

    def export(self, resource: TrainingSession, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        document = build_completed_workout_document(resource, user_id)
        validate_json_document(document, "completed_workout")
        rows = []
        for exercise in resource.exercises:
            for training_set in exercise.sets:
                load = training_set.load_details_json or {}
                load_display = (
                    f"{escape(str(load.get('normalized_total_kg')))} kg / {escape(str(load.get('calculated_total_lb')))} lb"
                    if load
                    else f"{training_set.weight_kg} kg"
                )
                rows.append(
                    "<tr>"
                    f"<td>{escape(exercise.name)}</td>"
                    f"<td>{training_set.set_number}</td>"
                    f"<td>{load_display}</td>"
                    f"<td>{escape(str(load.get('load_mode') or 'direct_total'))}</td>"
                    f"<td>{training_set.reps}</td>"
                    f"<td>{training_set.rir if training_set.rir is not None else '—'}</td>"
                    f"<td>{training_set.rpe if training_set.rpe is not None else '—'}</td>"
                    f"<td>{training_set.rest_seconds if training_set.rest_seconds is not None else '—'}</td>"
                    "</tr>"
                )
        summary = []
        if resource.duration_seconds is not None:
            summary.append(f"Duración: {resource.duration_seconds} s")
        if resource.average_heart_rate_bpm is not None:
            summary.append(f"FC promedio: {resource.average_heart_rate_bpm} bpm")
        if resource.calories_burned is not None:
            summary.append(f"Calorías: {resource.calories_burned}")
        summary_html = f"<p>{' · '.join(summary)}</p>" if summary else ""
        html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Sesión {resource.id}</title>
<style>body{{font-family:system-ui;margin:2rem;color:#172033}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #94a3b8;padding:.5rem;text-align:left}}@media print{{button{{display:none}}}}</style>
</head><body><button onclick="window.print()">Imprimir</button>
<h1>{escape(resource.training_plan.name)}</h1>
<p>Sesión: {escape(document['data']['performed_at'])} · versión {resource.training_plan_version.version_number}</p>
{summary_html}
<table><thead><tr><th>Ejercicio</th><th>Serie</th><th>Carga</th><th>Modo</th><th>Reps</th><th>RIR</th><th>RPE</th><th>Descanso s</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>"""
        return ExportArtifact(
            content=html.encode("utf-8"),
            mimetype="text/html",
            extension="html",
            inline=True,
        )
