from flask import current_app, g, request, send_file

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import ApiError, success
from app.api_v1.schemas import json_body
from app.services.portability_export import (
    PortabilityExportError, create_export, delete_export, export_job_document,
    get_export, list_exports, resolve_export_download,
)
from app.services.portability_import import (
    PortabilityImportError, apply_import, delete_import, get_import,
    import_job_document, inspect_import, list_imports,
)


def _translate(error):
    raise ApiError(error.code, str(error), error.status) from error


def _audit(event: str, public_id: str, state: str, counts: dict | None = None) -> None:
    current_app.logger.info(
        "api_event=%s user_public=%s portability_id=%s state=%s sections=%s total=%s",
        event, g.api_user.public_id[:8], public_id[:8], state,
        len(counts or {}), sum((counts or {}).values()),
    )


@api_v1_bp.post("/mobile/portability/exports")
@bearer_required
def portability_export_create():
    payload = json_body()
    try:
        job, replay = create_export(g.api_user, payload, request.headers.get("Idempotency-Key", ""))
    except PortabilityExportError as error:
        _translate(error)
    _audit("portability_export_replayed" if replay else "portability_export_created", job.public_id, job.state, job.counts_json)
    return success(export_job_document(job), status=200 if replay else 201)


@api_v1_bp.get("/mobile/portability/exports")
@bearer_required
def portability_export_list():
    return success({"items": [export_job_document(job) for job in list_exports(g.api_user.id)]})


@api_v1_bp.get("/mobile/portability/exports/<public_id>")
@bearer_required
def portability_export_detail(public_id):
    job = get_export(g.api_user.id, public_id)
    if job is None:
        raise ApiError("not_found", "Exportación no encontrada.", 404)
    return success(export_job_document(job))


@api_v1_bp.get("/mobile/portability/exports/<public_id>/download")
@bearer_required
def portability_export_download(public_id):
    job = get_export(g.api_user.id, public_id)
    if job is None:
        raise ApiError("not_found", "Exportación no encontrada.", 404)
    try:
        path = resolve_export_download(job, g.api_user.id)
    except PortabilityExportError as error:
        _translate(error)
    response = send_file(path, mimetype=job.artifact.media_type, as_attachment=True,
        download_name=job.artifact.filename, conditional=False, etag=False, max_age=0)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@api_v1_bp.delete("/mobile/portability/exports/<public_id>")
@bearer_required
def portability_export_delete(public_id):
    job = get_export(g.api_user.id, public_id)
    if job is None:
        raise ApiError("not_found", "Exportación no encontrada.", 404)
    try:
        delete_export(job, g.api_user.id)
    except PortabilityExportError as error:
        _translate(error)
    _audit("portability_export_deleted", job.public_id, job.state)
    return success({"export_id": job.public_id, "state": "deleted"})


def _inspect_upload():
    if not request.content_type or "multipart/form-data" not in request.content_type:
        raise ApiError("unsupported_media_type", "Se requiere multipart/form-data.", 415)
    try:
        job = inspect_import(g.api_user, request.files.get("file"), request.form.get("sections"))
    except PortabilityImportError as error:
        _translate(error)
    _audit("portability_import_inspected", job.public_id, job.state, job.counts_json)
    return success(import_job_document(job), status=201)


@api_v1_bp.post("/mobile/portability/imports/inspect")
@bearer_required
def portability_import_inspect():
    return _inspect_upload()


@api_v1_bp.post("/mobile/portability/imports")
@bearer_required
def portability_import_create():
    return _inspect_upload()


@api_v1_bp.get("/mobile/portability/imports")
@bearer_required
def portability_import_list():
    return success({"items": [import_job_document(job) for job in list_imports(g.api_user.id)]})


@api_v1_bp.get("/mobile/portability/imports/<public_id>")
@bearer_required
def portability_import_detail(public_id):
    job = get_import(g.api_user.id, public_id)
    if job is None:
        raise ApiError("not_found", "Importación no encontrada.", 404)
    return success(import_job_document(job))


@api_v1_bp.post("/mobile/portability/imports/<public_id>/apply")
@bearer_required
def portability_import_apply(public_id):
    job = get_import(g.api_user.id, public_id)
    if job is None:
        raise ApiError("not_found", "Importación no encontrada.", 404)
    try:
        result = apply_import(job, g.api_user.id, json_body(), request.headers.get("Idempotency-Key", ""))
    except PortabilityImportError as error:
        _translate(error)
    _audit("portability_import_applied", job.public_id, result["state"], result["counts"])
    return success(result)


@api_v1_bp.delete("/mobile/portability/imports/<public_id>")
@bearer_required
def portability_import_delete(public_id):
    job = get_import(g.api_user.id, public_id)
    if job is None:
        raise ApiError("not_found", "Importación no encontrada.", 404)
    try:
        delete_import(job, g.api_user.id)
    except PortabilityImportError as error:
        _translate(error)
    _audit("portability_import_deleted", public_id, "deleted")
    return success({"import_id": public_id, "state": "deleted"})
