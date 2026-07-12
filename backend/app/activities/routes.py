from copy import deepcopy
from io import BytesIO

from flask import abort, render_template, send_file
from flask_login import current_user, login_required

from app.activities import activities_bp
from app.extensions import db
from app.models import Activity, Route
from app.services.exporters.base import serialize_json
from app.services.validation import validate_json_document


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
    return render_template("activities/detail.html", activity=activity)


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
