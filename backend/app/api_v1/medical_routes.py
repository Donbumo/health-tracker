from __future__ import annotations

from datetime import date
from pathlib import Path

from flask import Response, current_app, g, request, send_file

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import ApiError, success
from app.api_v1.schemas import json_body
from app.extensions import db
from app.services.medical_documents import (
    delete_document,
    inspect_upload,
    permanent_delete_study,
    resolve_download,
    store_document,
)
from app.services.medical_import import confirm_import, csv_template, preview_import
from app.services.medical_records import (
    archive_study,
    conversion_catalog,
    create_result,
    create_study,
    delete_result,
    duplicates_for_study,
    lab_history,
    list_studies,
    marker_catalog,
    owned_document,
    owned_study,
    patch_result,
    patch_study,
    serialize_document,
    serialize_result,
    serialize_study,
    study_results,
)
from app.services.mobile_sync import claim_idempotency, finish_idempotency


def _audit_api(event: str, entity_type: str, state: str | None = None) -> None:
    current_app.logger.info(
        "api_event=%s user_public=%s device=%s entity_type=%s state=%s",
        event,
        g.api_user.public_id[:8],
        g.api_session.device.public_device_id[:8],
        entity_type,
        state or "none",
    )


def _idempotent(operation: str, payload: dict, handler):
    record, replay = claim_idempotency(
        user_id=g.api_user.id,
        device_id=g.api_session.device_id,
        raw_key=request.headers.get("Idempotency-Key", ""),
        operation=operation,
        payload=payload,
    )
    if replay:
        return success(record.response_body_json, status=record.response_status)
    cleanup: list[Path] = []
    try:
        handled = handler()
        if len(handled) == 2:
            data, status = handled
        else:
            data, status, cleanup = handled
        finish_idempotency(record, data, status)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    for path in cleanup:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # The database deletion already committed. Windows may still hold a
            # just-downloaded file briefly; report only a sanitized cleanup code.
            current_app.logger.warning("medical_file_cleanup_deferred code=file_busy")
    return success(data, status=status)


def _query_date(name: str) -> date | None:
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        from app.services.mobile_sync import MobileSyncError
        raise MobileSyncError("invalid_date", f"{name} debe usar YYYY-MM-DD.") from error


@api_v1_bp.get("/mobile/medical-studies")
@bearer_required
def medical_study_list():
    return success(list_studies(
        g.api_user.id,
        limit=request.args.get("limit", 50, type=int),
        offset=request.args.get("offset", 0, type=int),
        state=request.args.get("state"),
        study_type=request.args.get("study_type"),
        date_from=_query_date("date_from"),
        date_to=_query_date("date_to"),
    ))


@api_v1_bp.post("/mobile/medical-studies")
@bearer_required
def medical_study_create():
    payload = json_body()

    def execute():
        row = create_study(g.api_user.id, payload)
        _audit_api("medical_study_created", "medical_study", row.state)
        return serialize_study(row, detail=True), 201

    return _idempotent("medical_study_create", payload, execute)


@api_v1_bp.get("/mobile/medical-studies/<public_id>")
@bearer_required
def medical_study_detail(public_id):
    row = owned_study(g.api_user.id, public_id)
    value = serialize_study(row, detail=True)
    value["duplicates"] = duplicates_for_study(g.api_user.id, row)
    return success(value)


@api_v1_bp.patch("/mobile/medical-studies/<public_id>")
@bearer_required
def medical_study_patch(public_id):
    payload = json_body()

    def execute():
        row = patch_study(g.api_user.id, public_id, payload)
        _audit_api("medical_study_updated", "medical_study", row.state)
        return serialize_study(row, detail=True), 200

    return _idempotent(f"medical_study_patch:{public_id}", payload, execute)


@api_v1_bp.post("/mobile/medical-studies/<public_id>/archive")
@bearer_required
def medical_study_archive(public_id):
    payload = json_body()

    def execute():
        row = archive_study(g.api_user.id, public_id, payload)
        _audit_api("medical_study_archived", "medical_study", row.state)
        return serialize_study(row, detail=True), 200

    return _idempotent(f"medical_study_archive:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/medical-studies/<public_id>")
@bearer_required
def medical_study_delete(public_id):
    payload = json_body()

    def execute():
        data, paths = permanent_delete_study(g.api_user.id, public_id, payload)
        _audit_api("medical_study_permanently_deleted", "medical_study", "deleted")
        return data, 200, paths

    return _idempotent(f"medical_study_delete:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/medical-studies/<public_id>/results")
@bearer_required
def medical_result_list(public_id):
    return success(study_results(g.api_user.id, public_id))


@api_v1_bp.post("/mobile/medical-studies/<public_id>/results")
@bearer_required
def medical_result_create(public_id):
    payload = json_body()

    def execute():
        row = create_result(g.api_user.id, public_id, payload)
        _audit_api("medical_result_created", "lab_result")
        return serialize_result(row, include_revisions=True), 201

    return _idempotent(f"medical_result_create:{public_id}", payload, execute)


@api_v1_bp.patch("/mobile/lab-results/<public_id>")
@bearer_required
def medical_result_patch(public_id):
    payload = json_body()

    def execute():
        row = patch_result(g.api_user.id, public_id, payload)
        _audit_api("medical_result_corrected", "lab_result")
        return serialize_result(row, include_revisions=True), 200

    return _idempotent(f"medical_result_patch:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/lab-results/<public_id>")
@bearer_required
def medical_result_delete(public_id):
    payload = json_body()

    def execute():
        data = delete_result(g.api_user.id, public_id, payload)
        _audit_api("medical_result_deleted", "lab_result", "deleted")
        return data, 200

    return _idempotent(f"medical_result_delete:{public_id}", payload, execute)


@api_v1_bp.post("/mobile/medical-studies/<public_id>/documents")
@bearer_required
def medical_document_create(public_id):
    if not request.content_type or "multipart/form-data" not in request.content_type:
        raise ApiError("unsupported_media_type", "Se requiere multipart/form-data.", 415)
    study = owned_study(g.api_user.id, public_id)
    content, filename, mime, sha256 = inspect_upload(request.files.get("file"))
    document_type = request.form.get("document_type", "original")
    idempotency_payload = {
        "study_public_id": study.public_id,
        "sha256": sha256,
        "size_bytes": len(content),
        "mime_type": mime,
        "document_type": document_type,
    }

    def execute():
        row, duplicate = store_document(
            study,
            content=content,
            filename=filename,
            mime_type=mime,
            sha256=sha256,
            document_type=document_type,
        )
        _audit_api("medical_document_duplicate" if duplicate else "medical_document_added", "medical_document")
        data = serialize_document(row)
        data["duplicate"] = duplicate
        return data, 200 if duplicate else 201

    return _idempotent(f"medical_document_create:{public_id}", idempotency_payload, execute)


@api_v1_bp.get("/mobile/medical-documents/<public_id>")
@bearer_required
def medical_document_detail(public_id):
    return success(serialize_document(owned_document(g.api_user.id, public_id)))


@api_v1_bp.get("/mobile/medical-documents/<public_id>/download")
@bearer_required
def medical_document_download(public_id):
    row = owned_document(g.api_user.id, public_id)
    path = resolve_download(row, g.api_user.id)
    response = send_file(
        path,
        mimetype=row.mime_type,
        as_attachment=True,
        download_name=row.original_filename,
        conditional=False,
        etag=False,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox"
    return response


@api_v1_bp.delete("/mobile/medical-documents/<public_id>")
@bearer_required
def medical_document_delete(public_id):
    payload = json_body()

    def execute():
        data, path = delete_document(g.api_user.id, public_id, payload)
        _audit_api("medical_document_deleted", "medical_document", "deleted")
        return data, 200, [path] if path else []

    return _idempotent(f"medical_document_delete:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/lab-markers")
@bearer_required
def medical_marker_catalog():
    return success({
        "items": marker_catalog(request.args.get("q")),
        "conversion_allowlist": conversion_catalog(),
        "clinical_ranges_included": False,
    })


@api_v1_bp.get("/mobile/lab-history/<canonical_key>")
@bearer_required
def medical_marker_history(canonical_key):
    return success(lab_history(
        g.api_user.id,
        canonical_key,
        period=request.args.get("period", "all"),
        laboratory=request.args.get("laboratory"),
        unit=request.args.get("unit"),
        method=request.args.get("method"),
        source=request.args.get("source"),
        study_type=request.args.get("study_type"),
    ))


@api_v1_bp.post("/mobile/medical-imports/preview")
@bearer_required
def medical_import_preview():
    if not request.content_type or "multipart/form-data" not in request.content_type:
        raise ApiError("unsupported_media_type", "Se requiere multipart/form-data.", 415)
    value = preview_import(g.api_user.id, request.files.get("file"))
    _audit_api("medical_import_previewed", "medical_import", "valid" if value["valid"] else "invalid")
    return success(value)


@api_v1_bp.post("/mobile/medical-imports/confirm")
@bearer_required
def medical_import_confirm():
    payload = json_body(max_bytes=min(current_app.config["MEDICAL_DOCUMENT_MAX_BYTES"], 8 * 1024 * 1024))

    def execute():
        value = confirm_import(g.api_user.id, payload)
        _audit_api("medical_import_confirmed", "medical_import", value["state"])
        return value, 200

    return _idempotent("medical_import_confirm", payload, execute)


@api_v1_bp.get("/mobile/medical-imports/template.csv")
@bearer_required
def medical_import_template():
    response = Response(csv_template(), mimetype="text/csv")
    response.headers["Content-Disposition"] = 'attachment; filename="health_tracker_medical_lab_v1.csv"'
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
