"""Operator capability for a Coach progression, using Gym's official publisher."""
from __future__ import annotations

from app.services.ai.capabilities.types import ActionApplyResult, ActionCapability, CapabilityError
from app.services.gym_programs import GymError
from app.services.gym_progression_confirm import confirm, preview


FIELDS = ("program_id", "prescription_id", "program_revision", "proposed_load", "evidence")
SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "program_id": {"type": "string", "format": "uuid"},
    "prescription_id": {"type": "string", "pattern": "^[0-9]+:[0-9]+:[0-9]+$", "maxLength": 32},
    "program_revision": {"type": "integer", "minimum": 1},
    "proposed_load": {"type": ["string", "number"]},
    "evidence": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 500}},
}}


def _evaluation(user, payload):
    try:
        result = preview(user.id, payload["program_id"], payload["prescription_id"])
    except GymError as error:
        raise CapabilityError("progression_unavailable", str(error), error.status) from error
    evaluation = result["evaluation"]
    if (evaluation["state"] != "increase_load" or not evaluation.get("proposal")
            or not evaluation["proposal"].get("field_changes")):
        raise CapabilityError("progression_unavailable", "La progresión ya no está disponible.", 409)
    return result


def _owner_context(user, payload, _resource_context=None):
    result = _evaluation(user, payload)
    evaluation = result["evaluation"]
    if (evaluation["program_revision"] != payload.get("program_revision")
            or str(evaluation["proposal"]["load"]) != str(payload.get("proposed_load"))
            or evaluation["evidence"] != payload.get("evidence")):
        raise CapabilityError("revision_conflict", "La evidencia cambió. Revisa de nuevo la propuesta.", 409)
    return {"resource_type": "training_program", "public_id": payload["program_id"],
            "current_load": evaluation["current"].get("load"),
            "proposed_load": evaluation["proposal"]["load"],
            "unit": evaluation["current"].get("unit"),
            "exercise_name": evaluation["name"],
            "evidence": evaluation["evidence"]}


def _preview(_user, _payload, context):
    return {"fields": [], "exercise_name": context["exercise_name"],
            "current_load": context["current_load"], "proposed_load": context["proposed_load"],
            "unit": context["unit"], "evidence": context["evidence"]}


def _apply(user, draft, payload, _context, _now):
    _owner_context(user, payload)
    result = _evaluation(user, payload)
    source_hash = (draft.provenance_json or {}).get("_coach_source_hash")
    if not source_hash or result["evaluation"]["source_hash"] != source_hash:
        raise CapabilityError("revision_conflict", "La evidencia cambió. Revisa de nuevo la propuesta.", 409)
    try:
        plan, _duplicate = confirm(user.id, result["token"])
    except GymError as error:
        raise CapabilityError("revision_conflict", str(error), error.status) from error
    return ActionApplyResult("training_program", (plan.public_id,))


TRAINING_PROGRESSION_UPDATE = ActionCapability(
    action_id="training.progression.update", domain="training", entity="training_program",
    operation="update", label="Aplicar progresión de Gym",
    description="Prepara la progresión calculada por Gym; requiere preview y confirmación.",
    supported_fields=FIELDS, required_fields=FIELDS, optional_fields=(),
    input_schema=SCHEMA, apply_handler=_apply, owner_resolver=_owner_context,
    previewer=_preview, idempotency_policy="draft_uuid", context_required=True,
)
