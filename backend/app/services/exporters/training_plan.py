import csv
from io import StringIO

from app.models import TrainingPlan
from app.services.exporters.base import BaseExporter, ExportArtifact, serialize_json
from app.services.training_plans import get_active_version
from app.services.validation import validate_json_document


CSV_WARNING = (
    "CSV aplana semanas, días, ejercicios y series; puede perder estructura o metadatos."
)


class TrainingPlanJsonExporter(BaseExporter):
    format_name = "json"

    def export(self, resource: TrainingPlan, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        version = get_active_version(resource, user_id)
        validate_json_document(version.content, "training_plan")
        return ExportArtifact(
            content=serialize_json(version.content),
            mimetype="application/json",
            extension="json",
        )


class TrainingPlanCsvExporter(BaseExporter):
    format_name = "csv"
    fieldnames = (
        "plan_name",
        "version",
        "week_number",
        "week_name",
        "day_number",
        "day_name",
        "exercise_order",
        "exercise_name",
        "exercise_notes",
        "set_number",
        "reps",
        "reps_min",
        "reps_max",
        "duration_seconds",
        "distance_m",
        "target",
        "rest_seconds",
    )

    def export(self, resource: TrainingPlan, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        version = get_active_version(resource, user_id)
        validate_json_document(version.content, "training_plan")

        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=self.fieldnames)
        writer.writeheader()
        document = version.content
        for week in document["data"]["weeks"]:
            for day in week["days"]:
                if not day["exercises"]:
                    writer.writerow(
                        {
                            "plan_name": resource.name,
                            "version": version.version_number,
                            "week_number": week["week_number"],
                            "week_name": week.get("name", ""),
                            "day_number": day["day_number"],
                            "day_name": day["name"],
                        }
                    )
                    continue
                for exercise in day["exercises"]:
                    for planned_set in exercise["sets"]:
                        writer.writerow(
                            {
                                "plan_name": resource.name,
                                "version": version.version_number,
                                "week_number": week["week_number"],
                                "week_name": week.get("name", ""),
                                "day_number": day["day_number"],
                                "day_name": day["name"],
                                "exercise_order": exercise["exercise_order"],
                                "exercise_name": exercise["name"],
                                "exercise_notes": exercise.get("notes", ""),
                                "set_number": planned_set["set_number"],
                                "reps": planned_set.get("reps", ""),
                                "reps_min": planned_set.get("reps_min", ""),
                                "reps_max": planned_set.get("reps_max", ""),
                                "duration_seconds": planned_set.get(
                                    "duration_seconds", ""
                                ),
                                "distance_m": planned_set.get("distance_m", ""),
                                "target": planned_set.get("target", ""),
                                "rest_seconds": planned_set.get("rest_seconds", ""),
                            }
                        )

        return ExportArtifact(
            content=output.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            extension="csv",
            warning=CSV_WARNING,
        )
