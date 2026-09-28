"""Explicit owner-scoped links. Suggestions never participate in resolution."""
import unicodedata
import uuid

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

from app.extensions import db
from app.models import Exercise, ExerciseAlias, ExerciseCatalogSource, TrainingPlan, TrainingPlanVersion
from app.services.exercise_catalog import external_catalog, resolve_external
from app.services.exercise_identity import normalize_exercise_name
from app.services.gym_programs import GymError, catalog, lock_user


def search_text(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


# Search vocabulary only, not aliases or asserted equivalences. References come
# exclusively from the installed catalog; unknown variants remain pending.
SEARCH_HINTS = (
    (('prensa',), ('leg press',)),
    (('curl', 'femoral', 'sentado'), ('seated leg curl',)),
    (('jalon', 'neutro'), ('v-bar pulldown',)),
    (('press', 'pecho'), ('chest press', 'bench press')),
    (('remo', 't'), ('t-bar row',)),
    (('smith', 'rdl'), ('smith machine stiff-legged deadlift',)),
    (('hip', 'thrust'), ('hip thrust',)),
)


def candidates(name, identities, entries, query=''):
    if query:
        terms = [search_text(query.strip())]
    else:
        exact = resolve_external(name, [], entries)
        if exact:
            return exact
        text = search_text(name)
        words = set(text.replace('-', ' ').split())
        terms = next((list(terms) for required, terms in SEARCH_HINTS if set(required) <= words), [text])
    matches = [row for row in entries if any(term in search_text(row.name) for term in terms)]
    if not query:
        words = set(search_text(name).split())
        if 'prensa' in words:
            matches = [r for r in matches if 'quadriceps' in r.details.get('primary_muscles', [])]
        if 'maquina' in words:
            matches = [r for r in matches if r.details.get('equipment') == 'machine']
    return matches


def review_items(user_id):
    identities = catalog(user_id)
    names = {n: item for item in identities for n in [item.normalized_name, *(a.normalized_name for a in item.aliases if a.user_id == user_id)]}
    by_public_id = {item.public_id: item for item in identities}
    targets = {item.normalized_name: {'name': item.canonical_name, 'identity': item} for item in identities}
    versions = db.session.execute(db.select(TrainingPlanVersion).join(TrainingPlan, TrainingPlan.id == TrainingPlanVersion.training_plan_id).where(
        TrainingPlan.user_id == user_id, TrainingPlanVersion.user_id == user_id,
        TrainingPlan.deleted_at.is_(None), TrainingPlanVersion.version_number == TrainingPlan.active_version_number,
    )).scalars()
    for version in versions:
        for week in version.content['data']['weeks']:
            for day in week['days']:
                for exercise in day['exercises']:
                    key = normalize_exercise_name(exercise['name'])
                    identity = by_public_id.get(exercise.get('exercise_id')) or names.get(key)
                    targets.setdefault(key, {'name': exercise['name'], 'identity': identity})
    entries = external_catalog()
    by_id = {row.id: row for row in entries}
    for item in targets.values():
        identity = item['identity']
        item['linked'] = by_id.get(identity.external_catalog_id) if identity else None
        item['candidates'] = candidates(item['name'], identities, entries)
    return sorted(targets.values(), key=lambda item: item['name'].casefold()), identities, entries


def review_target(user_id, name):
    try:
        key = normalize_exercise_name(name)
    except ValueError as error:
        raise GymError('Ejercicio no encontrado.', 404) from error
    items, identities, entries = review_items(user_id)
    item = next((item for item in items if normalize_exercise_name(item['name']) == key), None)
    if item is None:
        raise GymError('Ejercicio no encontrado.', 404)
    return item, identities, entries


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='exercise-link-review-v1')


def _decision(user_id, item, row):
    state = db.session.get(ExerciseCatalogSource, row.source)
    if state is None or not state.active_snapshot:
        raise GymError('El catálogo no está disponible.', 409)
    identity = item['identity']
    return {'owner': user_id, 'name': item['name'], 'identity': identity.public_id if identity else None,
            'previous': identity.external_catalog_id if identity else None,
            'reference': row.public_id, 'revision': state.active_snapshot}


def decision_token(user_id, item, row):
    return _serializer().dumps(_decision(user_id, item, row))


def confirm_link(user_id, name, reference_id, token):
    lock_user(user_id)
    db.session.expire_all()  # Refresh the state reviewed before waiting on the owner lock.
    item, _, entries = review_target(user_id, name)
    row = next((row for row in entries if row.public_id == reference_id), None)
    if row is None:
        raise GymError('Referencia no disponible; revisa los candidatos.', 409)
    try:
        reviewed = _serializer().loads(token, max_age=1800)
    except BadData as error:
        raise GymError('La revisión expiró; vuelve a elegir el ejercicio.', 409) from error
    expected = _decision(user_id, item, row)
    if reviewed != expected:
        # A retry of exactly the same decision is harmless; a stale different
        # choice must never overwrite a newer link.
        retry = dict(expected, previous=reviewed.get('previous'), identity=reviewed.get('identity')) if isinstance(reviewed, dict) else None
        if not (item['identity'] and item['identity'].external_catalog_id == row.id and reviewed == retry):
            raise GymError('El vínculo o el catálogo cambió; vuelve a revisarlo.', 409)
    identity = item['identity']
    if identity is None:
        identity = Exercise(user_id=user_id, public_id=str(uuid.uuid4()), canonical_name=item['name'], normalized_name=normalize_exercise_name(item['name']))
        db.session.add(identity)
        db.session.flush()
    identity.external_catalog_id = row.id
    normalized = normalize_exercise_name(item['name'])
    alias = db.session.execute(db.select(ExerciseAlias).where(ExerciseAlias.user_id == user_id, ExerciseAlias.normalized_name == normalized)).scalar_one_or_none()
    if alias and alias.exercise_id != identity.id:
        raise GymError('El nombre ya pertenece a otra identidad.', 409)
    if not alias:
        db.session.add(ExerciseAlias(user_id=user_id, exercise_id=identity.id, alias_name=item['name'], normalized_name=normalized))
    return identity
