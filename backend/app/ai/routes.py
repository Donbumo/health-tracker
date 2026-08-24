from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.ai import ai_bp
from app.extensions import db
from app.services.ai.conversations import AIConversationService, AIServiceError


@ai_bp.after_request
def private_ai_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _web_error(error: AIServiceError):
    db.session.rollback()
    if error.status == 404:
        abort(404)
    flash(error.safe_message, "danger" if error.status >= 500 else "warning")


@ai_bp.get("")
@login_required
def index():
    service = AIConversationService()
    conversations = service.list(current_user.id)
    return render_template(
        "ai/index.html",
        conversations=conversations,
        ai_status=service.status(current_user._get_current_object()),
    )


@ai_bp.post("/conversations")
@login_required
def create_conversation():
    service = AIConversationService()
    status = service.status(current_user._get_current_object())
    if status["state"] != "available":
        flash(status["reason"] or "La función AI no está disponible.", "warning")
        return redirect(url_for("ai.index"))
    try:
        row = service.create(current_user.id)
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    return redirect(url_for("ai.conversation", conversation_id=row.public_id))


@ai_bp.get("/conversations/<conversation_id>")
@login_required
def conversation(conversation_id: str):
    service = AIConversationService()
    try:
        row = service.get(current_user.id, conversation_id)
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    return render_template(
        "ai/conversation.html",
        conversation=row,
        ai_status=service.status(current_user._get_current_object()),
    )


@ai_bp.post("/conversations/<conversation_id>/messages")
@login_required
def send_message(conversation_id: str):
    try:
        AIConversationService().send_message(
            current_user._get_current_object(),
            conversation_id,
            request.form.get("content"),
        )
    except AIServiceError as error:
        _web_error(error)
    return redirect(url_for("ai.conversation", conversation_id=conversation_id))


@ai_bp.post("/conversations/<conversation_id>/retry")
@login_required
def retry_message(conversation_id: str):
    try:
        AIConversationService().retry_last_turn(
            current_user._get_current_object(), conversation_id
        )
    except AIServiceError as error:
        _web_error(error)
    return redirect(url_for("ai.conversation", conversation_id=conversation_id))


@ai_bp.post("/conversations/<conversation_id>/delete")
@login_required
def delete_conversation(conversation_id: str):
    if request.form.get("confirm_delete") != "yes":
        flash("Confirma el borrado de la conversación.", "warning")
        return redirect(url_for("ai.conversation", conversation_id=conversation_id))
    try:
        AIConversationService().delete(current_user.id, conversation_id)
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    flash("Conversación eliminada.", "success")
    return redirect(url_for("ai.index"))


@ai_bp.post("/settings/remote-consent")
@login_required
def remote_consent():
    enabled = request.form.get("remote_consent") == "enabled"
    try:
        AIConversationService.set_remote_consent(current_user.id, enabled)
    except AIServiceError as error:
        _web_error(error)
    else:
        flash(
            "AI remota habilitada con consentimiento explícito."
            if enabled
            else "AI remota deshabilitada.",
            "success",
        )
    return redirect(url_for("ai.index"))


@ai_bp.post("/drafts/<draft_id>/confirm")
@login_required
def confirm_draft(draft_id: str):
    service = AIConversationService()
    try:
        draft = service.get_draft(current_user.id, draft_id)
        ambiguous_fields = [
            str(value)
            for value in (draft.payload_json or {}).get("ambiguous_fields", [])
            if str(value)
        ]
        if draft.draft_type == "body_measurement":
            edits = {
                "weight": request.form.get("weight"),
                "unit": request.form.get("unit"),
            }
            resolved_ambiguous = {
                field_name
                for field_name in ("weight", "unit")
                if edits.get(field_name) not in (None, "")
            }
            for field_name in (
                "recorded_at",
                "body_fat_percent",
                "muscle_mass_kg",
                "water_percent",
                "visceral_fat",
                "bmr_kcal",
                "bmi",
                "notes",
            ):
                value = request.form.get(field_name)
                if value not in (None, ""):
                    edits[field_name] = value
                    resolved_ambiguous.add(field_name)
            edits["ambiguous_fields"] = [
                field_name
                for field_name in ambiguous_fields
                if field_name not in resolved_ambiguous
            ]
        elif draft.draft_type == "food_entry":
            items = []
            for index, original in enumerate((draft.payload_json or {}).get("items", [])):
                item = dict(original)
                item.update(
                    {
                        "name": request.form.get(f"item_name_{index}"),
                        "quantity": request.form.get(f"item_quantity_{index}") or None,
                        "unit": request.form.get(f"item_unit_{index}") or None,
                    }
                )
                for field_name in (
                    "calories_kcal",
                    "protein_g",
                    "fat_g",
                    "net_carbs_g",
                    "total_carbs_g",
                    "fiber_g",
                    "sugar_g",
                    "sodium_mg",
                    "notes",
                ):
                    value = request.form.get(f"item_{field_name}_{index}")
                    if value not in (None, ""):
                        item[field_name] = value
                items.append(item)
            edits = {
                "date": request.form.get("date") or None,
                "meal_type": request.form.get("meal_type"),
                "meal_name": request.form.get("meal_name") or None,
                "items": items,
            }
            if edits["date"] is None:
                edits.pop("date")
            resolved_ambiguous = {
                field_name
                for field_name in ("date", "meal_type", "meal_name")
                if edits.get(field_name) not in (None, "")
            }
            for field_name in (
                "name",
                "quantity",
                "unit",
                "calories_kcal",
                "protein_g",
                "fat_g",
                "net_carbs_g",
                "total_carbs_g",
                "fiber_g",
                "sugar_g",
                "sodium_mg",
                "notes",
            ):
                if any(item.get(field_name) not in (None, "") for item in items):
                    resolved_ambiguous.add(field_name)
            edits["ambiguous_fields"] = [
                field_name
                for field_name in ambiguous_fields
                if field_name not in resolved_ambiguous
            ]
        else:
            edits = None
        row = service.confirm_draft(
            current_user._get_current_object(), draft_id, edits=edits
        )
    except AIServiceError as error:
        _web_error(error)
        conversation_id = request.form.get("conversation_id")
        if conversation_id:
            return redirect(
                url_for("ai.conversation", conversation_id=conversation_id)
            )
        return redirect(url_for("ai.index"))
    flash(
        "Borrador aplicado."
        if row.status == "applied"
        else "El borrador no cambió.",
        "success",
    )
    return redirect(
        url_for("ai.conversation", conversation_id=row.conversation.public_id)
    )


@ai_bp.post("/drafts/<draft_id>/reject")
@login_required
def reject_draft(draft_id: str):
    try:
        row = AIConversationService().reject_draft(current_user.id, draft_id)
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    flash("Borrador rechazado; no se escribió ningún dato.", "success")
    return redirect(
        url_for("ai.conversation", conversation_id=row.conversation.public_id)
    )
