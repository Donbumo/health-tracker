from copy import deepcopy
from io import BytesIO

from flask import abort, render_template, send_file
from flask_login import current_user, login_required

from app.activities import activities_bp
from app.extensions import db
from app.models import Activity, Route
from app.services.exporters.base import serialize_json
from app.services.validation import validate_json_document
from app.services.activity_interchange import (
    activity_laps as interchange_laps,
    activity_route as interchange_route,
    activity_series as interchange_series,
    plan_actual_comparison,
)


@activities_bp.get("/activities")
@login_required
def list_activities():
    records = db.session.execute(
        db.select(Activity)
        .where(Activity.user_id == current_user.id)
        .order_by(Activity.started_at.desc(), Activity.id.desc())
    ).scalars().all()
    return render_template("activities/list.html", activities=records)


@activities_bp.get("/activities/<int:activity_id>")
@login_required
def activity_detail(activity_id: int):
    activity = _activity_or_404(activity_id)
    route = interchange_route(activity, current_user.id)
    series = interchange_series(activity, current_user.id, offset=0, limit=300, downsample=180)
    metric_name, metric_values = _preferred_series(series["items"])
    comparison = plan_actual_comparison(activity, current_user.id) if activity.plan_link else None
    return render_template(
        "activities/detail.html", activity=activity,
        laps=interchange_laps(activity, current_user.id), route=route,
        route_svg_points=_svg_points([(row["lon"], row["lat"]) for row in route.get("points", [])]),
        series=series, metric_name=metric_name,
        series_svg_points=_svg_points(list(enumerate(metric_values))), comparison=comparison,
    )


@activities_bp.get("/activities/<int:activity_id>/export.json")
@login_required
def export_activity_json(activity_id: int):
    activity = _activity_or_404(activity_id)
    document = _activity_document(activity)
    return send_file(
        BytesIO(serialize_json(document)),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"activity_{activity.id}.json",
    )


@activities_bp.get("/routes")
@login_required
def list_routes():
    records = db.session.execute(
        db.select(Route)
        .where(Route.user_id == current_user.id)
        .order_by(Route.created_at.desc(), Route.id.desc())
    ).scalars().all()
    return render_template("routes/list.html", routes=records)


@activities_bp.get("/routes/<int:route_id>")
@login_required
def route_detail(route_id: int):
    route = _route_or_404(route_id)
    return render_template("routes/detail.html", route=route)


@activities_bp.get("/routes/<int:route_id>/export.json")
@login_required
def export_route_json(route_id: int):
    route = _route_or_404(route_id)
    document = _route_document(route)
    return send_file(
        BytesIO(serialize_json(document)),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"route_{route.id}.json",
    )


def _activity_or_404(activity_id: int) -> Activity:
    activity = db.session.execute(
        db.select(Activity).where(
            Activity.id == activity_id,
            Activity.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if activity is None:
        abort(404)
    return activity


def _route_or_404(route_id: int) -> Route:
    route = db.session.execute(
        db.select(Route).where(
            Route.id == route_id,
            Route.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if route is None:
        abort(404)
    return route


def _activity_document(activity: Activity) -> dict:
    document = deepcopy(activity.canonical_json)
    document["user_id"] = current_user.id
    document["source_file_id"] = activity.source_file_id
    validate_json_document(document, "activity")
    return document


def _route_document(route: Route) -> dict:
    document = deepcopy(route.canonical_json)
    document["user_id"] = current_user.id
    document["source_file_id"] = route.source_file_id
    validate_json_document(document, "route")
    return document


def _preferred_series(items: list[dict]) -> tuple[str | None, list[float]]:
    for field in ("heart_rate", "speed", "pace", "power", "cadence", "elevation", "distance"):
        values = [float(row[field]) for row in items if isinstance(row.get(field), (int, float))]
        if len(values) >= 2:
            return field, values
    return None, []


def _svg_points(points: list[tuple[float, float]]) -> str:
    if len(points) < 2:
        return ""
    xs, ys = [float(row[0]) for row in points], [float(row[1]) for row in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max(max_x - min_x, 1e-12), max(max_y - min_y, 1e-12)
    return " ".join(f"{5 + 90 * (x - min_x) / span_x:.2f},{95 - 90 * (y - min_y) / span_y:.2f}" for x, y in zip(xs, ys))
