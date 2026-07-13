from typing import Any

from app.services.exporters.activity_route import (
    activity_laps_capability,
    activity_track_capability,
    always_capability,
    gps_capability,
    render_activity_gpx,
    render_activity_json,
    render_activity_laps_csv,
    render_activity_summary_csv,
    render_activity_tcx,
    render_activity_track_csv,
    render_route_gpx,
    render_route_json,
    render_route_points_csv,
    render_route_tcx,
    unsupported_fit_capability,
)
from app.services.exporters.base import ExportArtifact, ExportError, ExportSpec
from app.services.exporters.training_advanced import (
    plan_capability,
    render_plan_csv,
    render_plan_erg,
    render_plan_html,
    render_plan_json,
    render_plan_mrc,
    render_plan_pdf,
    render_plan_zwo,
    render_session_csv,
    render_session_html,
    render_session_json,
    render_session_pdf,
    session_capability,
    structured_capability,
)


class ExporterRegistry:
    def __init__(self) -> None:
        self._specs = {(spec.domain, spec.format_name): spec for spec in _specs()}

    def get(self, domain: str, format_name: str) -> ExportSpec:
        spec = self._specs.get((domain, format_name))
        if spec is None:
            raise ExportError("Unsupported export domain or format")
        return spec

    def formats_for(self, domain: str) -> tuple[ExportSpec, ...]:
        return tuple(spec for (candidate, _), spec in self._specs.items() if candidate == domain)

    @property
    def capabilities(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._specs))


def _specs() -> list[ExportSpec]:
    return [
        _spec("activity", "json", "json", "application/json", render_activity_json, always_capability),
        _spec("activity", "csv", "csv", "text/csv", render_activity_summary_csv, always_capability, suffix="summary"),
        _spec("activity", "csv_track", "csv", "text/csv", render_activity_track_csv, activity_track_capability, suffix="track"),
        _spec("activity", "csv_laps", "csv", "text/csv", render_activity_laps_csv, activity_laps_capability, suffix="laps"),
        _spec("activity", "gpx", "gpx", "application/gpx+xml", render_activity_gpx, gps_capability),
        _spec("activity", "tcx", "tcx", "application/vnd.garmin.tcx+xml", render_activity_tcx, gps_capability),
        _spec("activity", "fit", "fit", "application/vnd.ant.fit", _unsupported_render, unsupported_fit_capability),
        _spec("route", "json", "json", "application/json", render_route_json, always_capability),
        _spec("route", "csv", "csv", "text/csv", render_route_points_csv, always_capability, suffix="points"),
        _spec("route", "gpx", "gpx", "application/gpx+xml", render_route_gpx, gps_capability),
        _spec("route", "tcx", "tcx", "application/vnd.garmin.tcx+xml", render_route_tcx, gps_capability),
        _spec("route", "fit", "fit", "application/vnd.ant.fit", _unsupported_render, unsupported_fit_capability),
        _spec("training_plan", "json", "json", "application/json", render_plan_json, plan_capability),
        _spec("training_plan", "csv", "csv", "text/csv", render_plan_csv, plan_capability),
        _spec("training_plan", "html", "html", "text/html", render_plan_html, plan_capability),
        _spec("training_plan", "pdf", "pdf", "application/pdf", render_plan_pdf, plan_capability),
        _spec("training_plan", "zwo", "zwo", "application/vnd.zwift.workout+xml", render_plan_zwo, structured_capability("percent")),
        _spec("training_plan", "erg", "erg", "application/x-erg", render_plan_erg, structured_capability("watts")),
        _spec("training_plan", "mrc", "mrc", "application/x-mrc", render_plan_mrc, structured_capability("percent")),
        _spec("training_plan", "fit", "fit", "application/vnd.ant.fit", _unsupported_render, unsupported_fit_capability),
        _spec("training_session", "json", "json", "application/json", render_session_json, session_capability),
        _spec("training_session", "csv", "csv", "text/csv", render_session_csv, session_capability),
        _spec("training_session", "html", "html", "text/html", render_session_html, session_capability),
        _spec("training_session", "pdf", "pdf", "application/pdf", render_session_pdf, session_capability),
    ]


def _spec(
    domain: str,
    format_name: str,
    extension: str,
    media_type: str,
    render,
    capability,
    *,
    suffix: str | None = None,
) -> ExportSpec:
    def filename(resource: Any, context: dict[str, Any]) -> str:
        source_id = getattr(resource, "id", "export")
        base = getattr(resource, "name", None) or f"{domain}_{source_id}"
        version = context.get("version_id")
        parts = [str(base)]
        if version:
            parts.append(f"version_{version}")
        if suffix:
            parts.append(suffix)
        return "_".join(parts)

    return ExportSpec(domain, format_name, extension, media_type, render, filename, capability)


def _unsupported_render(resource: Any, user_id: int, context: dict[str, Any]) -> ExportArtifact:
    raise ExportError("This exporter is not available")
