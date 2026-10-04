"""Owner-bound preview/confirm for deterministic prescription updates.

Reusable by a future training.prescription.update draft flow. No AI registration.
Caller commits; all mutations go through the official program publisher.
"""
import hashlib

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

from app.extensions import db
from app.models import TrainingPlanVersion
from app.services.gym_programs import GymError, lock_user, owned_plan, publish_program_document
from app.services.gym_progression import RULE_ID, RULE_VERSION, changed_document
from app.services.gym_strength import StrengthReader
from app.services.training_plans import get_active_version, serialize_training_plan

STALE = "La rutina cambió. Revisa de nuevo la propuesta."
TOKEN_TTL_SECONDS = 1800


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="gym-progression-confirm-v1")


def _digest(document):
    return hashlib.sha256(serialize_training_plan(document)).hexdigest()


def preview(user_id, program_id, prescription_id):
    reader = StrengthReader(user_id)
    context = reader.context(program_id, prescription_id)
    evaluation = reader.evaluate(context)
    if not context["plan"].gym_active or context["plan"].status != "active":
        raise GymError("Activa esta rutina antes de preparar un cambio.", 409)
    if not evaluation["proposal"] or not evaluation["proposal"]["field_changes"]:
        raise GymError("Esta evaluación no tiene un cambio de prescripción aplicable.", 409)
    changes = evaluation["proposal"]["field_changes"]
    target = changed_document(context["version"].content, prescription_id, changes)
    payload = {"owner": user_id, "program": program_id, "revision": evaluation["program_revision"],
               "version": evaluation["revision_id"], "prescription": prescription_id,
               "rule_id": RULE_ID, "rule_version": RULE_VERSION, "source": evaluation["source_hash"],
               "changes": changes, "target": _digest(target)}
    return {"evaluation": evaluation, "token": _serializer().dumps(payload)}


def confirm(user_id, token):
    try:
        payload = _serializer().loads(token, max_age=TOKEN_TTL_SECONDS)
    except (BadData, TypeError) as error:
        raise GymError("La propuesta expiró o no es válida. Prepara una nueva.", 409) from error
    if not isinstance(payload, dict) or payload.get("owner") != user_id:
        raise GymError("Propuesta no encontrada.", 404)
    if payload.get("rule_id") != RULE_ID or payload.get("rule_version") != RULE_VERSION:
        raise GymError(STALE, 409)
    lock_user(user_id)
    plan = owned_plan(user_id, payload["program"], lock=True)
    if not plan.gym_active or plan.status != "active":
        raise GymError(STALE, 409)
    # Locking reads are current reads under MariaDB REPEATABLE READ, including
    # relationships. Do not depend on an earlier request's authentication snapshot.
    reader = StrengthReader(user_id, lock=True)
    context = reader.context(plan.public_id, payload["prescription"])
    current = context["version"]
    if (plan.revision == payload["revision"] + 1 and current.sha256 == payload["target"]):
        return plan, True
    if plan.revision != payload["revision"] or current.public_id != payload["version"]:
        raise GymError(STALE, 409)
    evaluation = reader.evaluate(context)
    if (evaluation["source_hash"] != payload["source"] or not evaluation["proposal"]
            or evaluation["proposal"]["field_changes"] != payload["changes"]):
        raise GymError(STALE, 409)
    document = changed_document(current.content, payload["prescription"], payload["changes"])
    digest = _digest(document)
    if digest != payload["target"]:
        raise GymError(STALE, 409)
    # The general publisher can reactivate identical historical content. This flow
    # promises a NEW revision, so an old identical document requires fresh review.
    if any(v.sha256 == digest for v in context["plan"].versions):
        raise GymError(STALE, 409)
    plan, duplicate = publish_program_document(document, user_id, plan_id=plan.public_id,
                                                base_revision=payload["revision"])
    version = get_active_version(plan, user_id)
    version.change_reason = f"Progresión confirmada · {RULE_VERSION}"
    db.session.flush()
    return plan, duplicate
