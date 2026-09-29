"""Durable working state; publishing remains an explicit atomic operation."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer

from app.extensions import db
from app.models import GymImportDraft, TrainingPlan
from app.services.gym_programs import GymError, lock_user, owned_plan, resolve_draft, standard_document, confirm_program, preview_token, catalog
from app.services.importers.routine_draft import RoutineImportDraft, RoutineParseError, MAX_BYTES, MAX_DAYS, MAX_EXERCISES, MAX_SETS

STALE = "Este borrador cambió en otra pestaña. Recarga para continuar."
EXERCISE_FIELDS = {'raw_name', 'name', 'notes', 'sets', 'create_new', 'resolved_exercise_id', 'resolved_catalog_id', 'catalog_revision', 'external_source', 'external_id', 'mapping_choice'}


def pending(user_id):
    return db.session.execute(db.select(GymImportDraft).where(GymImportDraft.user_id == user_id, GymImportDraft.state == 'pending').order_by(GymImportDraft.updated_at.desc())).scalars().all()


def owned(user_id, public_id, *, lock=False):
    if lock:
        lock_user(user_id)
    query = db.select(GymImportDraft).where(GymImportDraft.user_id == user_id, GymImportDraft.public_id == public_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.session.execute(query).scalar_one_or_none()
    if row is None:
        raise GymError('Borrador no encontrado.', 404)
    return row


def _pending(row, revision):
    if row.state != 'pending':
        raise GymError('Este borrador ya está cerrado.', 409)
    if type(revision) is not int or revision != row.revision:
        raise GymError(STALE, 409)


def _fields(value, allowed):
    if not isinstance(value, dict) or set(value) - allowed:
        raise GymError('Campos de borrador inválidos.')


def validate_working(raw, user_id):
    """Allow incomplete edits, but not unbounded or arbitrary client payloads."""
    _fields(raw, {'program', 'days'})
    if len(json.dumps(raw, allow_nan=False).encode()) > MAX_BYTES:
        raise GymError('Borrador mayor a 2 MB.', 413)
    _fields(raw.get('program'), {'name', 'description'})
    for key, limit in (('name', 200), ('description', 5000)):
        value = raw['program'].get(key)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise GymError('Texto de programa inválido.')
    if not isinstance(raw.get('days'), list) or len(raw['days']) > MAX_DAYS:
        raise GymError('Demasiados días.')
    set_fields = set(json.loads((Path(current_app.config['SCHEMA_ROOT']) / 'training_plan.schema.json').read_text(encoding='utf-8'))['$defs']['set']['properties'])
    own_ids = {item.public_id for item in catalog(user_id)}
    from app.services.exercise_catalog import external_catalog
    reference_ids = {item.public_id for item in external_catalog()}
    for day in raw['days']:
        _fields(day, {'name', 'order', 'notes', 'exercises'})
        if not isinstance(day.get('name'), str) or len(day['name']) > 200 or not isinstance(day.get('exercises'), list) or len(day['exercises']) > MAX_EXERCISES:
            raise GymError('Día inválido.')
        if day.get('notes') is not None and (not isinstance(day['notes'], str) or len(day['notes']) > 5000):
            raise GymError('Notas de día inválidas.')
        for ex in day['exercises']:
            _fields(ex, EXERCISE_FIELDS)
            if not isinstance(ex.get('raw_name'), str) or len(ex['raw_name']) > 200 or not isinstance(ex.get('sets'), list) or len(ex['sets']) > MAX_SETS:
                raise GymError('Ejercicio inválido.')
            if ex.get('mapping_choice') not in (None, 'unresolved', 'new', 'none', 'identity', 'catalog'):
                raise GymError('Selección inválida.')
            for key, limit in (('name', 200), ('notes', 2000), ('resolved_exercise_id', 200), ('resolved_catalog_id', 200), ('catalog_revision', 200), ('external_source', 200), ('external_id', 200)):
                if ex.get(key) is not None and (not isinstance(ex[key], str) or len(ex[key]) > limit):
                    raise GymError('Campo de ejercicio inválido.')
            if ex.get('resolved_exercise_id') and ex['resolved_exercise_id'] not in own_ids:
                raise GymError('Ejercicio no encontrado.', 404)
            if ex.get('resolved_catalog_id') and ex['resolved_catalog_id'] not in reference_ids:
                raise GymError('Referencia no disponible.', 404)
            if 'create_new' in ex and type(ex['create_new']) is not bool:
                raise GymError('Selección inválida.')
            for target in ex['sets']:
                _fields(target, set_fields)


def materialize(row):
    return RoutineImportDraft(**copy.deepcopy(row.payload_json))


def _serializer():
    # Valid only while this owner-bound draft revision remains pending. No upload TTL.
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='gym-import-draft-confirm-v1')


def status(row):
    draft = materialize(row)
    error = None
    try:
        resolve_draft(draft, row.user_id)
        standard_document(draft, row.user_id)
        ready = not draft.unresolved
    except (ValueError, TypeError, KeyError) as exc:
        ready = False
        error = str(exc) if isinstance(exc, (GymError, RoutineParseError)) else 'Revisa los días y objetivos del borrador.'
    return {'revision': row.revision, 'ready': ready, 'error': error, 'unresolved_count': len(draft.unresolved),
            'saved_at': row.updated_at.isoformat(),
            'token': _serializer().dumps([row.user_id, row.public_id, row.revision])}


def create(draft, user_id, *, plan=None, base_revision=None, source_type='manual'):
    validate_working({'program': draft.program, 'days': draft.days}, user_id)
    resolve_draft(draft, user_id)
    standard_document(draft, user_id)
    # Only normalized content and provenance survive parsing. No source bytes/ref.
    draft.source_ref = None
    row = GymImportDraft(user_id=user_id, payload_json=draft.to_dict(), source_type=source_type,
                         target_plan_id=plan.id if plan else None, target_public_id=plan.public_id if plan else None, base_revision=base_revision)
    db.session.add(row)
    db.session.flush()
    return row


def set_mapping(draft, day, exercise, value):
    if type(day) is not int or type(exercise) is not int or day < 0 or exercise < 0 or not isinstance(value, str) or len(value) > 200:
        raise GymError('Selección inválida.')
    try:
        ex = draft.days[day]['exercises'][exercise]
    except (IndexError, KeyError) as error:
        raise GymError('Ejercicio no encontrado.', 404) from error
    for key in ('resolved_exercise_id', 'resolved_catalog_id', 'catalog_revision', 'external_source', 'external_id', 'name'):
        ex.pop(key, None)
    ex['create_new'] = value in ('new', 'none')
    ex['mapping_choice'] = value if value in ('new', 'none') else 'unresolved'
    if value.startswith('catalog:'):
        ex['resolved_catalog_id'] = value[8:]
        ex['mapping_choice'] = 'catalog'
    elif value and value not in ('new', 'none'):
        ex['resolved_exercise_id'] = value
        ex['mapping_choice'] = 'identity'


def save(user_id, public_id, revision, change):
    row = owned(user_id, public_id, lock=True)
    _pending(row, revision)
    draft = materialize(row)
    if change.get('action') == 'mapping':
        _fields(change, {'action', 'day', 'exercise', 'value'})
        set_mapping(draft, change.get('day'), change.get('exercise'), change.get('value'))
        # Mapping choices must be valid owner/catalog references now.
        resolve_draft(draft, user_id)
    elif change.get('action') == 'edit':
        _fields(change, {'action', 'draft'})
        raw = change.get('draft')
        validate_working(raw, user_id)
        draft.program, draft.days = copy.deepcopy(raw['program']), copy.deepcopy(raw['days'])
        # Draft selections are never personal mappings until confirmation.
    else:
        raise GymError('Cambio inválido.')
    row.payload_json = draft.to_dict()
    row.revision += 1
    row.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    return row


def confirm(user_id, public_id, revision, token):
    row = owned(user_id, public_id, lock=True)
    try:
        decision = _serializer().loads(token)
    except BadData as error:
        raise GymError('Reabre el borrador para confirmar. Tus cambios siguen guardados.', 409) from error
    if decision != [user_id, row.public_id, revision]:
        raise GymError(STALE, 409)
    if row.state == 'completed' and revision == row.revision - 1:
        plan = db.session.execute(db.select(TrainingPlan).where(TrainingPlan.id == row.result_plan_id, TrainingPlan.user_id == user_id)).scalar_one_or_none()
        if plan is None:
            raise GymError('El resultado ya no está disponible.', 409)
        return plan, True
    _pending(row, revision)
    if row.target_public_id:
        owned_plan(user_id, row.target_public_id)
    draft = materialize(row)
    plan, duplicate = confirm_program(draft, user_id, preview_token(draft, user_id, row.target_public_id, row.base_revision), plan_id=row.target_public_id, base_revision=row.base_revision)
    row.state = 'completed'
    row.result_plan_id = plan.id
    row.revision += 1
    row.updated_at = datetime.now(timezone.utc)
    # Keep a small durable result for HTTP retries, discard the working content.
    row.payload_json = {}
    db.session.flush()
    return plan, duplicate


def cancel(user_id, public_id, revision):
    row = owned(user_id, public_id, lock=True)
    _pending(row, revision)
    row.state = 'cancelled'
    row.payload_json = {}
    row.revision += 1
    row.updated_at = datetime.now(timezone.utc)
    return row
