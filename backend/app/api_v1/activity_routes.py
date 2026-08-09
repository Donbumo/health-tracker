from __future__ import annotations

from datetime import date
from io import BytesIO
import re

from flask import Response, current_app, g, request, send_file

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import ApiError, failure, success
from app.api_v1.schemas import json_body
from app.extensions import db
from app.services.activity_interchange import (
    apply_import_job,
    ActivityInterchangeError,
    archive_activity,
    activity_laps,
    activity_route,
    activity_series,
    create_import_job,
    delete_activity,
    delete_import_job,
    detach_plan_link,
    export_activity,
    inspect_import_job,
    list_activities,
    list_import_jobs,
    normalized_activity_document,
    owned_activity,
    owned_import_job,
    patch_activity,
    plan_actual_comparison,
    plan_candidates,
    remove_activity_route,
    serialize_activity,
    serialize_import_job,
    serialize_plan_link,
    set_plan_link,
)
from app.services.mobile_sync import claim_idempotency, finish_idempotency


@api_v1_bp.errorhandler(ActivityInterchangeError)
def handle_activity_error(error):
    return failure(error.code, error.message, error.status, error.details)


def _audit(event: str, entity_type: str, state: str | None = None) -> None:
    current_app.logger.info(
        "api_event=%s user_public=%s device=%s entity_type=%s state=%s",
        event, g.api_user.public_id[:8], g.api_session.device.public_device_id[:8],
        entity_type, state or "none",
    )


def _mutation(operation: str, payload: dict, handler, *, rollback_cleanup=None, commit_cleanup=None):
    rollback_cleanup = rollback_cleanup if rollback_cleanup is not None else []
    commit_cleanup = commit_cleanup if commit_cleanup is not None else []
    record, replay = claim_idempotency(
        user_id=g.api_user.id,
        device_id=g.api_session.device_id,
        raw_key=request.headers.get("Idempotency-Key", ""),
        operation=operation,
        payload=payload,
    )
    if replay:
        return success(record.response_body_json, status=record.response_status)
    try:
        data, status = handler()
        finish_idempotency(record, data, status)
        db.session.commit()
    except Exception:
        db.session.rollback()
        for path in rollback_cleanup:
            path.unlink(missing_ok=True)
        raise
    for path in commit_cleanup:
        path.unlink(missing_ok=True)
    return success(data, status=status)


@api_v1_bp.post("/mobile/activities/imports")
@bearer_required
def activity_import_create():
    if not request.content_type or "multipart/form-data" not in request.content_type:
        raise ApiError("unsupported_media_type", "Se requiere multipart/form-data.", 415)
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError("file_required", "Selecciona un archivo de actividad.", 400)
    maximum = current_app.config["ACTIVITY_FILE_MAX_BYTES"]
    content = upload.stream.read(maximum + 1)
    if not content:
        raise ApiError("empty_file", "El archivo está vacío.", 400)
    if len(content) > maximum:
        raise ApiError("file_too_large", "El archivo supera el límite permitido.", 413)
    job, replay = create_import_job(
        user_id=g.api_user.id, content=content, filename=upload.filename,
        mime_type=upload.mimetype, idempotency_key=request.headers.get("Idempotency-Key", ""),
        route_policy=request.form.get("route_policy", "keep"),
        redact_start_meters=request.form.get("redact_start_meters", "0"),
        redact_end_meters=request.form.get("redact_end_meters", "0"),
        strong_plan_public_id=request.form.get("planned_workout_id"),
    )
    _audit("activity_import_replayed" if replay else "activity_import_created", "activity_import", job.state)
    return success(serialize_import_job(job), status=200 if replay else 201)


@api_v1_bp.get("/mobile/activities/imports")
@bearer_required
def activity_import_list():
    return success({"items": list_import_jobs(g.api_user.id, limit=request.args.get("limit", 50, type=int))})


@api_v1_bp.get("/mobile/activities/imports/<public_id>")
@bearer_required
def activity_import_detail(public_id):
    return success(serialize_import_job(owned_import_job(g.api_user.id, public_id)))


@api_v1_bp.post("/mobile/activities/imports/<public_id>/inspect")
@bearer_required
def activity_import_inspect(public_id):
    job = owned_import_job(g.api_user.id, public_id)
    data = inspect_import_job(job, g.api_user.id)
    _audit("activity_import_inspected", "activity_import", data["state"])
    return success(data)


@api_v1_bp.post("/mobile/activities/imports/<public_id>/apply")
@bearer_required
def activity_import_apply(public_id):
    payload = json_body()
    if payload not in ({}, {"confirm": True}):
        raise ApiError("invalid_request", "La confirmación de importación no es válida.", 400)

    rollback_cleanup = []

    def execute():
        activity, duplicate = apply_import_job(
            owned_import_job(g.api_user.id, public_id), g.api_user.id,
            commit=False, rollback_cleanup=rollback_cleanup,
        )
        _audit("activity_import_duplicate" if duplicate else "activity_import_applied", "activity", "duplicate" if duplicate else "imported")
        return {"activity": serialize_activity(activity), "duplicate": duplicate}, 200 if duplicate else 201

    return _mutation(f"activity_import_apply:{public_id}", payload, execute, rollback_cleanup=rollback_cleanup)


@api_v1_bp.delete("/mobile/activities/imports/<public_id>")
@bearer_required
def activity_import_delete(public_id):
    payload = json_body()
    commit_cleanup = []

    def execute():
        delete_import_job(
            owned_import_job(g.api_user.id, public_id), g.api_user.id,
            commit=False, commit_cleanup=commit_cleanup,
        )
        _audit("activity_import_deleted", "activity_import", "deleted")
        return {"import_id": public_id, "deleted": True}, 200

    return _mutation(f"activity_import_delete:{public_id}", payload, execute, commit_cleanup=commit_cleanup)


@api_v1_bp.get("/mobile/activities")
@bearer_required
def activities_list():
    return success(list_activities(
        g.api_user.id, limit=request.args.get("limit", 50, type=int), cursor=request.args.get("cursor"),
        discipline=request.args.get("discipline"), status=request.args.get("status"),
        date_from=_date_arg("from"), date_to=_date_arg("to"),
    ))


@api_v1_bp.get("/mobile/activities/<public_id>")
@bearer_required
def activity_detail(public_id):
    return success(serialize_activity(owned_activity(g.api_user.id, public_id)))


@api_v1_bp.patch("/mobile/activities/<public_id>")
@bearer_required
def activity_patch(public_id):
    payload = json_body()
    return _mutation(
        f"activity_patch:{public_id}", payload,
        lambda: (serialize_activity(patch_activity(owned_activity(g.api_user.id, public_id), g.api_user.id, payload, commit=False)), 200),
    )


@api_v1_bp.post("/mobile/activities/<public_id>/archive")
@bearer_required
def activity_archive(public_id):
    payload = json_body()
    return _mutation(
        f"activity_archive:{public_id}", payload,
        lambda: (serialize_activity(archive_activity(owned_activity(g.api_user.id, public_id), g.api_user.id, payload.get("base_revision"), commit=False)), 200),
    )


@api_v1_bp.delete("/mobile/activities/<public_id>")
@bearer_required
def activity_delete(public_id):
    payload = json_body()
    commit_cleanup = []

    def execute():
        delete_activity(
            owned_activity(g.api_user.id, public_id), g.api_user.id, payload.get("base_revision"),
            commit=False, commit_cleanup=commit_cleanup,
        )
        _audit("activity_deleted", "activity", "deleted")
        return {"activity_id": public_id, "deleted": True}, 200

    return _mutation(f"activity_delete:{public_id}", payload, execute, commit_cleanup=commit_cleanup)


@api_v1_bp.get("/mobile/activities/<public_id>/laps")
@bearer_required
def activity_laps_list(public_id):
    activity = owned_activity(g.api_user.id, public_id)
    return success({"items": activity_laps(activity, g.api_user.id)})


@api_v1_bp.get("/mobile/activities/<public_id>/series")
@bearer_required
def activity_series_get(public_id):
    activity = owned_activity(g.api_user.id, public_id)
    return success(activity_series(
        activity, g.api_user.id, offset=request.args.get("offset", 0, type=int),
        limit=request.args.get("limit", 500, type=int), downsample=request.args.get("downsample", type=int),
    ))


@api_v1_bp.get("/mobile/activities/<public_id>/route")
@bearer_required
def activity_route_get(public_id):
    return success(activity_route(owned_activity(g.api_user.id, public_id), g.api_user.id))


@api_v1_bp.delete("/mobile/activities/<public_id>/route")
@bearer_required
def activity_route_delete(public_id):
    payload = json_body()
    commit_cleanup = []
    return _mutation(
        f"activity_route_delete:{public_id}", payload,
        lambda: (serialize_activity(remove_activity_route(
            owned_activity(g.api_user.id, public_id), g.api_user.id, payload.get("base_revision"),
            commit=False, commit_cleanup=commit_cleanup,
        )), 200),
        commit_cleanup=commit_cleanup,
    )


@api_v1_bp.get("/mobile/activities/<public_id>/export")
@bearer_required
def activity_export_get(public_id):
    activity = owned_activity(g.api_user.id, public_id)
    format_name = request.args.get("format", "json")
    content, mimetype, extension, warning = export_activity(
        activity, g.api_user.id, format_name=format_name,
        include_series=_bool_arg("include_series"), include_route=_bool_arg("include_route"),
    )
    response = send_file(
        BytesIO(content), mimetype=mimetype, as_attachment=True,
        download_name=f"activity_{activity.public_id}.{extension}", conditional=False, etag=False, max_age=0,
    )
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if warning:
        response.headers["X-Health-Tracker-Export-Warning"] = re.sub(r"[^\x20-\x7e]", "", warning)[:200]
    _audit("activity_exported", "activity", format_name)
    return response


@api_v1_bp.get("/mobile/activities/<public_id>/plan-candidates")
@bearer_required
def activity_plan_candidates(public_id):
    return success({"items": plan_candidates(owned_activity(g.api_user.id, public_id), g.api_user.id)})


@api_v1_bp.post("/mobile/activities/<public_id>/plan-link")
@bearer_required
def activity_plan_link(public_id):
    payload = json_body()
    return _mutation(
        f"activity_plan_link:{public_id}", payload,
        lambda: (serialize_plan_link(set_plan_link(owned_activity(g.api_user.id, public_id), g.api_user.id, payload, commit=False)), 200),
    )


@api_v1_bp.delete("/mobile/activities/<public_id>/plan-link")
@bearer_required
def activity_plan_unlink(public_id):
    payload = json_body()

    def execute():
        detach_plan_link(owned_activity(g.api_user.id, public_id), g.api_user.id, payload.get("base_revision"), commit=False)
        return {"activity_id": public_id, "state": "detached"}, 200

    return _mutation(f"activity_plan_unlink:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/activities/<public_id>/comparison")
@bearer_required
def activity_comparison(public_id):
    return success(plan_actual_comparison(owned_activity(g.api_user.id, public_id), g.api_user.id))


def _date_arg(name: str) -> date | None:
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ApiError("invalid_date", f"{name} debe usar YYYY-MM-DD.", 400) from error


def _bool_arg(name: str) -> bool:
    value = request.args.get(name, "false").casefold()
    if value not in {"true", "false", "1", "0"}:
        raise ApiError("invalid_boolean", f"{name} debe ser true o false.", 400)
    return value in {"true", "1"}
