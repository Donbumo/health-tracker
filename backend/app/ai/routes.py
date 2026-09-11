from dataclasses import dataclass
import json
import time

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.ai import ai_bp
from app.extensions import db
from app.services.ai.conversations import AIConversationService, AIServiceError
from app.services.ai.capabilities.composer import (
    AdaptivePromptComposer,
    AdaptiveTemplateComposer,
    INTENT_LABELS,
)
from app.services.ai.capabilities.context import load_action_context_token
from app.services.ai.capabilities.registry import AICapabilityRegistry
from app.services.ai.capabilities.types import AIIntentSpec, CapabilityError
from app.services.ai.template_registry import (
    AITemplateError,
    AITemplateRegistry,
    PERIOD_LABELS,
)


@ai_bp.after_request
def private_ai_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _web_error(error: AIServiceError):
    db.session.rollback()
    if error.status == 404:
        abort(404)
    flash(error.safe_message, "danger" if error.status >= 500 else "warning")


def _draft_form_edits(service: AIConversationService, draft) -> dict:
    if draft.draft_type == "body_measurement":
        edits = {"weight": request.form.get("weight"), "unit": request.form.get("unit")}
        for field_name in (
            "recorded_at", "body_fat_percent", "muscle_mass_kg", "water_percent",
            "visceral_fat", "bmr_kcal", "bmi", "notes",
        ):
            if field_name in request.form:
                edits[field_name] = request.form.get(field_name)
        return edits
    if draft.draft_type == "food_entry":
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
                "calories_kcal", "protein_g", "fat_g", "net_carbs_g",
                "total_carbs_g", "fiber_g", "sugar_g", "sodium_mg", "notes",
            ):
                if f"item_{field_name}_{index}" in request.form:
                    item[field_name] = request.form.get(f"item_{field_name}_{index}")
            items.append(item)
        return {
            "date": request.form.get("date"),
            "meal_type": request.form.get("meal_type"),
            "meal_name": request.form.get("meal_name"),
            "items": items,
        }
    capability = service._capability_for_draft(draft)
    properties = capability.input_schema.get("properties", {})
    edits = {}
    for field_name in capability.supported_fields:
        if field_name not in request.form or field_name.endswith("_fields") or field_name == "warnings":
            continue
        value = request.form.get(field_name)
        if value in (None, "") and field_name not in capability.required_fields:
            continue
        field_schema = properties.get(field_name, {})
        schema_type = field_schema.get("type")
        types = set(schema_type if isinstance(schema_type, list) else [schema_type])
        if "array" in types or "object" in types:
            try:
                parsed = json.loads(value or "null")
                if parsed is None and field_name not in capability.required_fields:
                    continue
                edits[field_name] = parsed
            except json.JSONDecodeError as error:
                raise AIServiceError(
                    "invalid_action_arguments", f"{field_name} debe usar JSON válido.", 422
                ) from error
        elif "integer" in types and value not in (None, ""):
            try:
                edits[field_name] = int(value)
            except ValueError as error:
                raise AIServiceError(
                    "invalid_action_arguments", f"{field_name} debe ser entero.", 422
                ) from error
        else:
            edits[field_name] = value
    return edits


@dataclass(frozen=True)
class _AISelection:
    template: object | None
    spec: AIIntentSpec
    period: str
    prompt: str
    title: str
    action_context_token: str | None = None
    action_context: dict | None = None

    @property
    def form_fields(self):
        if self.template is not None:
            result = {"template_id": self.template.id, "period": self.period}
        else:
            result = self.spec.as_query()
        if self.action_context_token:
            result["action_context"] = self.action_context_token
        return result

    @property
    def query(self):
        if self.template is not None:
            result = {"template": self.template.id, "period": self.period}
        else:
            result = self.spec.as_query()
        if self.action_context_token:
            result["action_context"] = self.action_context_token
        return result


def _selection(values):
    template_id = (values.get("template") or values.get("template_id") or "").strip()
    if template_id:
        try:
            template, period, prompt = AITemplateRegistry().prepare(
                template_id, values.get("period")
            )
            return _AISelection(
                template,
                template.intent_spec(period),
                period,
                prompt,
                template.title,
            )
        except AITemplateError as error:
            if error.status == 404:
                abort(404)
            abort(error.status, description=error.safe_message)
    capability_registry = AICapabilityRegistry()
    try:
        spec = capability_registry.parse(values)
        if spec is None:
            return None
        manifest = capability_registry.manifest(spec.domain)
        context_token = (values.get("action_context") or "").strip() or None
        action_context = None
        if context_token:
            context = load_action_context_token(context_token, user_id=current_user.id)
            resolved_action = capability_registry.resolve(spec).action
            if (
                resolved_action is None
                or context.action_capability_id != resolved_action.action_id
                or context.domain != resolved_action.domain
            ):
                raise CapabilityError(
                    "invalid_action_context",
                    "El contexto no corresponde a la acción seleccionada.",
                    403,
                )
            action_context = context.as_mapping()
            resolved_action.owner_resolver(current_user, {}, action_context)
        title = f"{INTENT_LABELS[spec.intent]} · {manifest.label}"
        prompt = AdaptivePromptComposer(capability_registry).compose(spec)
        return _AISelection(
            None,
            spec,
            spec.period,
            prompt,
            title,
            context_token,
            action_context,
        )
    except CapabilityError as error:
        abort(error.status, description=error.safe_message)


def _followups(template, period):
    if template is None:
        return ()
    registry = AITemplateRegistry()
    followups = []
    for template_id in template.suggested_followups:
        availability = registry.get(template_id)
        if not availability.available:
            continue
        candidate = availability.template
        candidate_period = (
            period if period in candidate.allowed_periods else candidate.default_period
        )
        followups.append(
            {
                "template": candidate,
                "period": candidate_period,
                "prompt": candidate.build_prompt(candidate_period),
            }
        )
    return tuple(followups)


def _render_index():
    service = AIConversationService()
    registry = AITemplateRegistry()
    resolution_started = time.perf_counter()
    selection = _selection(request.args)
    resolution_ms = max(0, round((time.perf_counter() - resolution_started) * 1000))
    catalog_started = time.perf_counter()
    adaptive_catalog = AdaptiveTemplateComposer(
        registry.capability_registry
    ).build(current_user.id, period=request.args.get("period") or "30d")
    catalog_ms = max(0, round((time.perf_counter() - catalog_started) * 1000))
    render_started = time.perf_counter()
    html = render_template(
        "ai/index.html",
        conversations=service.list(current_user.id),
        ai_status=service.status(current_user._get_current_object()),
        catalog=registry.templates,
        categories=registry.categories,
        period_labels=PERIOD_LABELS,
        intent_labels=INTENT_LABELS,
        adaptive_catalog=adaptive_catalog,
        selected_template=selection.template if selection else None,
        selected_title=selection.title if selection else None,
        selected_period=selection.period if selection else None,
        selected_spec=selection.spec if selection else None,
        selection_fields=selection.form_fields if selection else {},
        prepared_prompt=selection.prompt if selection else None,
    )
    render_ms = max(0, round((time.perf_counter() - render_started) * 1000))
    current_app.logger.info(
        (
            "ai_catalog_timing catalog_ms=%s availability_ms=%s "
            "recommendations_ms=%s intent_resolution_ms=%s render_ms=%s"
        ),
        catalog_ms,
        adaptive_catalog.availability_ms,
        adaptive_catalog.recommendations_ms,
        resolution_ms,
        render_ms,
    )
    return html


@ai_bp.get("")
@login_required
def index():
    return _render_index()


@ai_bp.get("/templates")
@login_required
def templates():
    return _render_index()


@ai_bp.post("/conversations")
@login_required
def create_conversation():
    service = AIConversationService()
    status = service.status(current_user._get_current_object())
    if status["state"] != "available":
        flash(status["reason"] or "La función AI no está disponible.", "warning")
        return redirect(url_for("ai.index"))
    selection = _selection(request.form)
    template = selection.template if selection else None
    period = selection.period if selection else None
    default_prompt = selection.prompt if selection else ""
    prepared_prompt = (request.form.get("content") or default_prompt).strip()
    prepared_prompt = prepared_prompt[: current_app.config["AI_MAX_INPUT_CHARS"]]
    if selection and not prepared_prompt:
        flash("Escribe el mensaje que deseas preparar.", "warning")
        return redirect(url_for("ai.index", **selection.query))
    try:
        row = service.create(current_user.id, title=selection.title if selection else None)
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    if selection is not None:
        current_app.logger.info(
            "ai_capability_selected intent=%s domain=%s metric_ids=%s period=%s preset=%s",
            selection.spec.intent.value,
            selection.spec.domain,
            ",".join(selection.spec.metrics) or "none",
            selection.spec.period,
            template.id if template else "none",
        )
        return render_template(
            "ai/conversation.html",
            conversation=row,
            ai_status=status,
            prepared_prompt=prepared_prompt,
            active_template=template,
            active_spec=selection.spec,
            selection_fields=selection.form_fields,
            active_title=selection.title,
            template_period=period,
            template_followups=(),
        )
    return redirect(
        url_for("ai.conversation", conversation_id=row.public_id)
    )


@ai_bp.get("/conversations/<conversation_id>")
@login_required
def conversation(conversation_id: str):
    service = AIConversationService()
    selection = _selection(request.args)
    template = selection.template if selection else None
    period = selection.period if selection else None
    try:
        row = service.get(current_user.id, conversation_id)
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    prepared_prompt = selection.prompt if selection and not row.messages else ""
    has_answer = bool(row.messages and row.messages[-1].role == "assistant")
    return render_template(
        "ai/conversation.html",
        conversation=row,
        ai_status=service.status(current_user._get_current_object()),
        prepared_prompt=prepared_prompt,
        active_template=template,
        active_spec=selection.spec if selection else None,
        selection_fields=selection.form_fields if selection else {},
        active_title=selection.title if selection else None,
        template_period=period,
        template_followups=_followups(template, period) if has_answer else (),
    )


@ai_bp.post("/conversations/<conversation_id>/messages")
@login_required
def send_message(conversation_id: str):
    selection = _selection(request.form)
    template = selection.template if selection else None
    period = selection.period if selection else None
    try:
        AIConversationService().send_message(
            current_user._get_current_object(),
            conversation_id,
            request.form.get("content"),
            template_id=template.id if template else None,
            intent_spec=selection.spec if selection else None,
            action_context=selection.action_context if selection else None,
        )
    except AIServiceError as error:
        _web_error(error)
    return redirect(
        url_for(
            "ai.conversation",
            conversation_id=conversation_id,
            **(selection.query if selection else {}),
        )
    )


@ai_bp.post("/conversations/<conversation_id>/retry")
@login_required
def retry_message(conversation_id: str):
    selection = _selection(request.form)
    template = selection.template if selection else None
    period = selection.period if selection else None
    try:
        AIConversationService().retry_last_turn(
            current_user._get_current_object(),
            conversation_id,
            template_id=template.id if template else None,
            intent_spec=selection.spec if selection else None,
            action_context=selection.action_context if selection else None,
        )
    except AIServiceError as error:
        _web_error(error)
    return redirect(
        url_for(
            "ai.conversation",
            conversation_id=conversation_id,
            **(selection.query if selection else {}),
        )
    )


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
        edits = _draft_form_edits(service, draft)
        ambiguous_fields = (draft.payload_json or {}).get("ambiguous_fields") or []
        if ambiguous_fields:
            supplied = {
                key for key, value in edits.items() if value not in (None, "", [])
            }
            if draft.draft_type == "food_entry":
                for field_name in (
                    "name", "quantity", "unit", "calories_kcal", "protein_g",
                    "fat_g", "net_carbs_g", "total_carbs_g", "fiber_g",
                    "sugar_g", "sodium_mg", "notes",
                ):
                    if any(
                        item.get(field_name) not in (None, "")
                        for item in edits.get("items", [])
                    ):
                        supplied.add(field_name)
            edits["ambiguous_fields"] = [
                field for field in ambiguous_fields if field not in supplied
            ]
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


@ai_bp.post("/drafts/<draft_id>/edit")
@login_required
def edit_draft(draft_id: str):
    service = AIConversationService()
    try:
        draft = service.get_draft(current_user.id, draft_id)
        row = service.edit_draft(
            current_user._get_current_object(),
            draft_id,
            _draft_form_edits(service, draft),
        )
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    flash("Borrador actualizado localmente; aún no se guardó ningún dato.", "success")
    return redirect(url_for("ai.conversation", conversation_id=row.conversation.public_id))


@ai_bp.post("/plans/<plan_id>/confirm")
@login_required
def confirm_plan(plan_id: str):
    try:
        result = AIConversationService().confirm_plan(
            current_user._get_current_object(), plan_id
        )
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    counts = result["counts"]
    flash(
        f"Plan procesado: {counts['applied']} aplicados, "
        f"{counts['pending_confirmation']} pendientes y {counts['failed']} con error.",
        "success" if not counts["failed"] else "warning",
    )
    row = AIConversationService().get_draft(current_user.id, result["drafts"][0]["id"])
    return redirect(url_for("ai.conversation", conversation_id=row.conversation.public_id))


@ai_bp.post("/plans/<plan_id>/retry")
@login_required
def retry_plan(plan_id: str):
    try:
        result = AIConversationService().retry_plan(
            current_user._get_current_object(), plan_id
        )
    except AIServiceError as error:
        _web_error(error)
        return redirect(url_for("ai.index"))
    counts = result["counts"]
    flash(
        f"Reintento seguro: {counts['applied']} aplicados y {counts['failed']} con error.",
        "success" if not counts["failed"] else "warning",
    )
    row = AIConversationService().get_draft(current_user.id, result["drafts"][0]["id"])
    return redirect(url_for("ai.conversation", conversation_id=row.conversation.public_id))


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
