"""Remove planning without deleting historical facts. Caller owns transaction."""
import json
from datetime import datetime, timezone
from sqlalchemy import or_
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature

from app.extensions import db
from app.models import (
    PlannedWorkout, SyncChange, TrainingPlan, TrainingPlanVersion,
    TrainingSession, TrainingSessionExercise, TrainingSet, WorkoutSessionDraft, TrainingPlanWorkout,
)
from app.services.gym_programs import GymError, lock_user
from app.services.mobile_sync import (
    MobileSyncError,
    PlannedWorkoutService,
    record_sync_change,
)


PENDING_DISCARD_CONFIRMATION = "DESCARTAR"


def _version_ids(plan):
    return db.select(TrainingPlanVersion.id).where(
        TrainingPlanVersion.training_plan_id == plan.id,
        TrainingPlanVersion.user_id == plan.user_id,
    )


def pending_artifacts(plan, *, lock=False):
    """Return owner-scoped artifacts that prevent routine deletion.

    The result deliberately excludes completed/abandoned sessions and terminal
    agenda rows.  Those records are historical facts or snapshots and remain
    valid references after the plan is removed from planning.
    """
    versions = _version_ids(plan)
    scope = lambda model: or_(
        model.training_plan_id == plan.id,
        model.training_plan_version_id.in_(versions),
    )

    def run(statement):
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return db.session.execute(statement).scalars().all()

    sessions = run(
        db.select(TrainingSession)
        .where(
            TrainingSession.user_id == plan.user_id,
            scope(TrainingSession),
            TrainingSession.status == "in_progress",
            TrainingSession.deleted_at.is_(None),
        )
        .order_by(TrainingSession.started_at.desc(), TrainingSession.id.desc())
    )
    planned = run(
        db.select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == plan.user_id,
            scope(PlannedWorkout),
            PlannedWorkout.status.in_(("planned", "in_progress")),
            PlannedWorkout.deleted_at.is_(None),
        )
        .order_by(PlannedWorkout.scheduled_for_date, PlannedWorkout.id)
    )
    drafts = run(
        db.select(WorkoutSessionDraft)
        .where(
            WorkoutSessionDraft.user_id == plan.user_id,
            scope(WorkoutSessionDraft),
        )
        .order_by(WorkoutSessionDraft.updated_at.desc(), WorkoutSessionDraft.id.desc())
    )
    return {"sessions": sessions, "planned": planned, "drafts": drafts}


def _confirmation_signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='gym-delete-pending-v1')


def deletion_preview(plan, *, lock=False):
    pending = pending_artifacts(plan, lock=lock)
    counts = {}
    for session in pending['sessions']:
        statement = db.select(TrainingSet.id).join(TrainingSessionExercise).where(
                TrainingSet.user_id == plan.user_id,
                TrainingSessionExercise.user_id == plan.user_id,
                TrainingSessionExercise.training_session_id == session.id,
            )
        if lock:
            statement = statement.with_for_update()
        counts[session.public_id] = len(db.session.execute(statement).all())
    history = db.session.execute(db.select(db.func.count(TrainingSession.id)).where(
        TrainingSession.user_id == plan.user_id,
        TrainingSession.training_plan_id == plan.id,
        TrainingSession.status.in_(['completed', 'abandoned']),
    )).scalar_one()
    snapshot = {
        'user': plan.user_id, 'plan': plan.public_id, 'revision': plan.revision,
        'pending': {kind: sorted((item.public_id, item.revision) for item in rows)
                    for kind, rows in pending.items()},
        'sets': counts, 'history': history,
    }
    # JSON round-trip gives lists on both sides of the signed comparison.
    snapshot = json.loads(json.dumps(snapshot))
    return dict(pending=pending, counts=counts, partial_sets=sum(counts.values()),
                empty_sessions=sum(count == 0 for count in counts.values()),
                history=history, snapshot=snapshot,
                token=_confirmation_signer().dumps(snapshot))


def _resolve_confirmed_pending(plan, token, partial_action, partial_confirmation):
    preview = deletion_preview(plan, lock=True)
    try:
        confirmed = _confirmation_signer().loads(token, max_age=1800)
    except (BadSignature, TypeError):
        raise GymError('La confirmación venció o es inválida; revisa de nuevo la eliminación.', 409)
    if confirmed != preview['snapshot']:
        raise GymError('Los pendientes cambiaron; revisa de nuevo lo que se eliminará.', 409)
    if preview['partial_sets']:
        if partial_action not in ('preserve', 'discard'):
            raise GymError('Elige conservar o descartar las series registradas.', 400)
        if partial_action == 'discard':
            _require_discard_confirmation(partial_confirmation)
    from app.services.gym_sessions import finish_session
    for session in preview['pending']['sessions']:
        if preview['counts'][session.public_id] and partial_action == 'preserve':
            finish_session(plan.user_id, session.public_id, 'abandoned')
        else:
            discard_pending_session(plan.user_id, plan.public_id, session.public_id,
                                    confirmation=PENDING_DISCARD_CONFIRMATION)
    for draft in preview['pending']['drafts']:
        discard_pending_draft(plan.user_id, plan.public_id, draft.public_id,
                              confirmation=PENDING_DISCARD_CONFIRMATION)
    for planned in preview['pending']['planned']:
        discard_pending_planned(plan.user_id, plan.public_id, planned.public_id,
                                confirmation=PENDING_DISCARD_CONFIRMATION)
    db.session.flush()


def _require_discard_confirmation(confirmation):
    if confirmation != PENDING_DISCARD_CONFIRMATION:
        raise GymError(
            "Escribe DESCARTAR para confirmar la eliminación de este pendiente.",
            400,
        )


def _locked_plan(user_id, public_id):
    plan = db.session.execute(
        db.select(TrainingPlan)
        .where(
            TrainingPlan.user_id == user_id,
            TrainingPlan.public_id == public_id,
            TrainingPlan.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if plan is None:
        raise GymError("Rutina no encontrada.", 404)
    return plan


def discard_pending_session(user_id, plan_public_id, session_public_id, *, confirmation):
    """Discard one in-progress session and its unfinalized sets."""
    _require_discard_confirmation(confirmation)
    lock_user(user_id)
    plan = _locked_plan(user_id, plan_public_id)
    session = db.session.execute(
        db.select(TrainingSession)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSession.public_id == session_public_id,
            TrainingSession.training_plan_id == plan.id,
            TrainingSession.deleted_at.is_(None),
            TrainingSession.status == "in_progress",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if session is None:
        raise GymError("Sesión pendiente no encontrada.", 404)
    exercises = db.select(TrainingSessionExercise.id).where(
        TrainingSessionExercise.training_session_id == session.id)
    if db.session.execute(db.select(TrainingSessionExercise.id).where(
        TrainingSessionExercise.training_session_id == session.id,
        TrainingSessionExercise.user_id != user_id,
    ).limit(1)).first() or db.session.execute(db.select(TrainingSet.id).where(
        TrainingSet.training_session_exercise_id.in_(exercises),
        TrainingSet.user_id != user_id,
    ).limit(1)).first():
        raise GymError('La sesión tiene referencias que deben conservarse.', 409)
    db.session.delete(session)
    db.session.flush()
    return True


def discard_pending_draft(user_id, plan_public_id, draft_public_id, *, confirmation):
    _require_discard_confirmation(confirmation)
    lock_user(user_id)
    plan = _locked_plan(user_id, plan_public_id)
    versions = _version_ids(plan)
    draft = db.session.execute(
        db.select(WorkoutSessionDraft)
        .where(
            WorkoutSessionDraft.user_id == user_id,
            WorkoutSessionDraft.public_id == draft_public_id,
            or_(
                WorkoutSessionDraft.training_plan_id == plan.id,
                WorkoutSessionDraft.training_plan_version_id.in_(versions),
            ),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if draft is None:
        raise GymError("Borrador pendiente no encontrado.", 404)
    db.session.delete(draft)
    db.session.flush()
    return True


def discard_pending_planned(user_id, plan_public_id, planned_public_id, *, confirmation):
    _require_discard_confirmation(confirmation)
    lock_user(user_id)
    plan = _locked_plan(user_id, plan_public_id)
    planned = db.session.execute(
        db.select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.public_id == planned_public_id,
            PlannedWorkout.training_plan_id == plan.id,
            PlannedWorkout.deleted_at.is_(None),
            PlannedWorkout.status.in_(("planned", "in_progress")),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if planned is None:
        raise GymError("Entrada de agenda pendiente no encontrada.", 404)
    # A preserved incomplete session must retain its agenda FK. The generic
    # mobile delete service intentionally refuses every linked session.
    linked = db.session.execute(db.select(TrainingSession).where(
        TrainingSession.planned_workout_id == planned.id,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if linked is not None and linked.user_id == user_id and linked.status == 'abandoned':
        planned.deleted_at = datetime.now(timezone.utc)
        planned.cancelled_at = planned.cancelled_at or planned.deleted_at
        planned.status = 'cancelled'
        planned.revision += 1
        planned.last_modified_by_device_id = None
        record_sync_change(user_id=user_id, entity_type='planned_workout',
                           entity_public_id=planned.public_id, operation='delete',
                           revision=planned.revision, payload=None, device_id=None)
        db.session.flush()
        return True
    try:
        PlannedWorkoutService.tombstone(
            planned, base_revision=planned.revision, device_id=None
        )
    except MobileSyncError as error:
        raise GymError(str(error), error.status) from error
    return True


def deletion_blocker(plan, *, lock=False):
    pending = pending_artifacts(plan, lock=lock)
    if pending["sessions"]:
        return "Esta rutina tiene una sesión pendiente. Revísala y descártala o ciérrala antes de eliminarla."
    if any(item.status == "in_progress" for item in pending["planned"]):
        return "Hay un entrenamiento de agenda en curso. Resuélvelo antes de eliminar la rutina."
    if pending["planned"]:
        return "Esta rutina tiene entrenamientos pendientes en la agenda. Resuélvelos antes de eliminarla."
    if pending["drafts"]:
        return "Esta rutina tiene borradores de sesión guardados. Revísalos y descártalos antes de eliminarla."
    return None


def delete_program(user_id, public_id, *, base_revision, confirmation,
                   pending_token=None, partial_action=None, partial_confirmation=None):
    if confirmation != 'ELIMINAR' or type(base_revision) is not int or base_revision < 1:
        raise GymError('Escribe ELIMINAR y confirma la revisión mostrada.', 400)
    lock_user(user_id)  # Same lock order as Gym start and import: user, then plan.
    plan = db.session.execute(db.select(TrainingPlan).where(
        TrainingPlan.user_id == user_id, TrainingPlan.public_id == public_id,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if plan is None or plan.deleted_at is not None:
        prior = db.session.execute(db.select(SyncChange.sequence).where(
            SyncChange.user_id == user_id, SyncChange.entity_type == 'training_plan',
            SyncChange.entity_public_id == public_id, SyncChange.operation == 'delete',
            SyncChange.revision == base_revision + 1,
        ).limit(1).with_for_update()).first()
        if prior:
            return False
        raise GymError('Rutina no encontrada.', 404)
    if plan.revision != base_revision:
        raise GymError('La rutina cambió; vuelve a revisar la eliminación.', 409)
    if pending_token:
        _resolve_confirmed_pending(plan, pending_token, partial_action, partial_confirmation)
    else:
        reason = deletion_blocker(plan, lock=True)
        if reason:
            raise GymError(reason, 409)
    # Any cross-owner child is an integrity problem, not permission to cascade.
    for model in (TrainingPlanVersion, TrainingPlanWorkout, TrainingSession, PlannedWorkout, WorkoutSessionDraft):
        if db.session.execute(db.select(model.id).where(
            model.training_plan_id == plan.id, model.user_id != user_id,
        ).limit(1).with_for_update()).first():
            raise GymError('La rutina tiene referencias que deben conservarse.', 409)
    # Defensive integrity check: even inconsistent foreign-owner references must
    # not cascade. Query existence only; never expose another owner's data.
    versions = db.select(TrainingPlanVersion.id).where(TrainingPlanVersion.training_plan_id == plan.id)
    guards = [~db.select(model.id).where(or_(
        model.training_plan_id == plan.id, model.training_plan_version_id.in_(versions),
    )).exists() for model in (TrainingSession, PlannedWorkout, WorkoutSessionDraft)]
    result = db.session.execute(db.delete(TrainingPlan).where(
        TrainingPlan.id == plan.id, TrainingPlan.user_id == user_id, *guards,
    ).execution_options(synchronize_session='fetch'))
    if result.rowcount != 1:
        # Historical sessions/closed agenda keep their immutable versions and FKs.
        # Never change status to archived: deleted is not an editable archive.
        # Recheck foreign version-only references before retaining the anchor.
        for model in (TrainingSession, PlannedWorkout, WorkoutSessionDraft):
            if db.session.execute(db.select(model.id).where(
                model.training_plan_version_id.in_(versions), model.user_id != user_id,
            ).limit(1)).first():
                raise GymError('La rutina tiene referencias que deben conservarse.', 409)
        plan.deleted_at = datetime.now(timezone.utc)
        plan.gym_active = False
        plan.revision = base_revision + 1
        db.session.execute(db.delete(TrainingPlanWorkout).where(
            TrainingPlanWorkout.training_plan_id == plan.id, TrainingPlanWorkout.user_id == user_id,
        ))
    record_sync_change(user_id=user_id, entity_type='training_plan',
                       entity_public_id=public_id, operation='delete',
                       revision=base_revision + 1, payload=None, device_id=None)
    return True
