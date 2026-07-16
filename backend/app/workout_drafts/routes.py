from flask import jsonify, request
from flask_login import current_user, login_required
from flask import current_app

from app.extensions import db
from app.services.workout_drafts import (
    WorkoutDraftError,
    create_draft,
    is_expired,
    owned_draft,
    serialize_draft,
    update_draft,
)
from app.workout_drafts import workout_drafts_bp


def _error(error: WorkoutDraftError):
    return jsonify(error={"code": error.code, "message": str(error)}), error.status_code


def _body_too_large():
    content_length = request.content_length
    return content_length is not None and content_length > (
        current_app.config["WORKOUT_DRAFT_MAX_BYTES"] + 4096
    )


@workout_drafts_bp.post("")
@login_required
def create():
    if _body_too_large():
        return jsonify(error={"code": "draft_too_large", "message": "The workout draft is too large."}), 413
    if not request.is_json:
        return jsonify(error={"code": "invalid_draft", "message": "JSON is required."}), 415
    body = request.get_json(silent=True) or {}
    try:
        draft, duplicate = create_draft(body.get("payload"), current_user.id)
    except WorkoutDraftError as error:
        db.session.rollback()
        return _error(error)
    return jsonify(
        data=serialize_draft(draft, include_payload=False),
        meta={"duplicate": duplicate, "result": "draft_saved"},
    ), (200 if duplicate else 201)


@workout_drafts_bp.get("/<public_id>")
@login_required
def detail(public_id: str):
    draft = owned_draft(public_id, current_user.id)
    if draft is None:
        return jsonify(error={"code": "not_found", "message": "Workout draft was not found."}), 404
    if is_expired(draft):
        return jsonify(error={"code": "draft_expired", "message": "Workout draft expired."}), 410
    return jsonify(data=serialize_draft(draft, include_payload=True))


@workout_drafts_bp.patch("/<public_id>")
@login_required
def update(public_id: str):
    draft = owned_draft(public_id, current_user.id)
    if draft is None:
        return jsonify(error={"code": "not_found", "message": "Workout draft was not found."}), 404
    if is_expired(draft):
        return jsonify(error={"code": "draft_expired", "message": "Workout draft expired."}), 410
    if _body_too_large():
        return jsonify(error={"code": "draft_too_large", "message": "The workout draft is too large."}), 413
    if not request.is_json:
        return jsonify(error={"code": "invalid_draft", "message": "JSON is required."}), 415
    body = request.get_json(silent=True) or {}
    revision = body.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        return jsonify(error={"code": "draft_conflict", "message": "Draft revision is required."}), 409
    try:
        draft, duplicate = update_draft(
            draft, body.get("payload"), current_user.id, revision
        )
    except WorkoutDraftError as error:
        db.session.rollback()
        return _error(error)
    return jsonify(
        data=serialize_draft(draft, include_payload=False),
        meta={"duplicate": duplicate, "result": "draft_saved"},
    )


@workout_drafts_bp.delete("/<public_id>")
@login_required
def delete(public_id: str):
    draft = owned_draft(public_id, current_user.id)
    if draft is None:
        return jsonify(error={"code": "not_found", "message": "Workout draft was not found."}), 404
    db.session.delete(draft)
    db.session.commit()
    return "", 204
