from flask import g

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import ApiError, success
from app.api_v1.schemas import json_body
from app.extensions import db
from app.services.ai.conversations import (
    AIConversationService,
    AIServiceError,
    serialize_conversation,
    serialize_draft,
    serialize_message,
)


def _service_error(error: AIServiceError):
    db.session.rollback()
    raise ApiError(error.code, error.safe_message, error.status) from error


def _require_available(service: AIConversationService) -> None:
    status = service.status(g.api_user)
    if status["state"] != "available":
        raise ApiError(
            "ai_unavailable",
            status["reason"] or "La función AI no está disponible.",
            503,
        )


@api_v1_bp.get("/ai/status")
@bearer_required
def ai_status():
    return success(AIConversationService.status(g.api_user))


@api_v1_bp.get("/ai/settings")
@bearer_required
def ai_settings():
    return success(AIConversationService.status(g.api_user))


@api_v1_bp.put("/ai/settings")
@bearer_required
def ai_update_settings():
    payload = json_body()
    if set(payload) != {"remote_consent_enabled"}:
        raise ApiError(
            "invalid_request", "Se requiere remote_consent_enabled.", 400
        )
    try:
        user = AIConversationService.set_remote_consent(
            g.api_user.id, payload["remote_consent_enabled"]
        )
    except AIServiceError as error:
        _service_error(error)
    return success(AIConversationService.status(user))


@api_v1_bp.post("/ai/conversations")
@bearer_required
def ai_create_conversation():
    service = AIConversationService()
    _require_available(service)
    payload = json_body()
    if set(payload) - {"title"}:
        raise ApiError("invalid_request", "La solicitud contiene campos no admitidos.", 400)
    title = payload.get("title")
    if title is not None and not isinstance(title, str):
        raise ApiError("invalid_request", "El título no es válido.", 400)
    try:
        row = service.create(g.api_user.id, title=title)
    except AIServiceError as error:
        _service_error(error)
    return success(serialize_conversation(row), status=201)


@api_v1_bp.get("/ai/conversations")
@bearer_required
def ai_list_conversations():
    try:
        rows = AIConversationService().list(g.api_user.id)
    except AIServiceError as error:
        _service_error(error)
    return success([serialize_conversation(row) for row in rows])


@api_v1_bp.get("/ai/conversations/<conversation_id>")
@bearer_required
def ai_get_conversation(conversation_id: str):
    try:
        row = AIConversationService().get(g.api_user.id, conversation_id)
    except AIServiceError as error:
        _service_error(error)
    return success(serialize_conversation(row, detail=True))


@api_v1_bp.delete("/ai/conversations/<conversation_id>")
@bearer_required
def ai_delete_conversation(conversation_id: str):
    try:
        AIConversationService().delete(g.api_user.id, conversation_id)
    except AIServiceError as error:
        _service_error(error)
    return success({"deleted": True, "id": conversation_id})


@api_v1_bp.post("/ai/conversations/<conversation_id>/messages")
@bearer_required
def ai_send_message(conversation_id: str):
    payload = json_body()
    if set(payload) - {"content", "attachments"}:
        raise ApiError("invalid_request", "La solicitud contiene campos no admitidos.", 400)
    try:
        message, drafts = AIConversationService().send_message(
            g.api_user,
            conversation_id,
            payload.get("content"),
            attachments=payload.get("attachments"),
        )
    except AIServiceError as error:
        _service_error(error)
    return success(
        {
            "message": serialize_message(message),
            "drafts": [serialize_draft(item) for item in drafts],
        },
        status=201,
    )


@api_v1_bp.post("/ai/conversations/<conversation_id>/retry")
@bearer_required
def ai_retry_message(conversation_id: str):
    payload = json_body()
    if payload:
        raise ApiError("invalid_request", "El reintento no acepta campos.", 400)
    try:
        message, drafts = AIConversationService().retry_last_turn(
            g.api_user, conversation_id
        )
    except AIServiceError as error:
        _service_error(error)
    return success(
        {
            "message": serialize_message(message),
            "drafts": [serialize_draft(item) for item in drafts],
        },
        status=201,
    )


@api_v1_bp.post("/ai/drafts/<draft_id>/confirm")
@bearer_required
def ai_confirm_draft(draft_id: str):
    payload = json_body()
    if set(payload) - {"payload"} or (
        "payload" in payload and not isinstance(payload["payload"], dict)
    ):
        raise ApiError(
            "invalid_request", "La corrección del borrador no es válida.", 400
        )
    try:
        row = AIConversationService().confirm_draft(
            g.api_user, draft_id, edits=payload.get("payload")
        )
    except AIServiceError as error:
        _service_error(error)
    return success(serialize_draft(row))


@api_v1_bp.patch("/ai/drafts/<draft_id>")
@bearer_required
def ai_edit_draft(draft_id: str):
    payload = json_body()
    if set(payload) != {"payload"} or not isinstance(payload["payload"], dict):
        raise ApiError("invalid_request", "La corrección del borrador no es válida.", 400)
    try:
        row = AIConversationService().edit_draft(
            g.api_user, draft_id, payload["payload"]
        )
    except AIServiceError as error:
        _service_error(error)
    return success(serialize_draft(row))


@api_v1_bp.post("/ai/drafts/<draft_id>/reject")
@bearer_required
def ai_reject_draft(draft_id: str):
    if json_body():
        raise ApiError("invalid_request", "El rechazo no acepta campos.", 400)
    try:
        row = AIConversationService().reject_draft(g.api_user.id, draft_id)
    except AIServiceError as error:
        _service_error(error)
    return success(serialize_draft(row))


@api_v1_bp.post("/ai/plans/<plan_id>/confirm")
@bearer_required
def ai_confirm_plan(plan_id: str):
    if json_body():
        raise ApiError("invalid_request", "La confirmación del plan no acepta campos.", 400)
    try:
        result = AIConversationService().confirm_plan(g.api_user, plan_id)
    except AIServiceError as error:
        _service_error(error)
    return success(result)


@api_v1_bp.post("/ai/plans/<plan_id>/retry")
@bearer_required
def ai_retry_plan(plan_id: str):
    if json_body():
        raise ApiError("invalid_request", "El reintento del plan no acepta campos.", 400)
    try:
        result = AIConversationService().retry_plan(g.api_user, plan_id)
    except AIServiceError as error:
        _service_error(error)
    return success(result)
