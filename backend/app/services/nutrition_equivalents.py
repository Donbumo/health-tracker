"""Local candidate review, outside canonical nutrient vectors and consumption.

Suggestions do not establish equivalence. No AI/provider call or definition
writer is exposed here. Only explicit selection may prepare an official draft.
"""
from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.services import food_catalog as catalog, nutrition_intelligence as ni
from app.services.nutrition_math import NUTRIENTS, NutritionError, ingredient


def personal(user_id, key):
    return catalog.detail(user_id, 'user:' + key)


def missing(food):
    # Qualified source evidence is preserved, rather than treated as absent.
    return [key for key in NUTRIENTS
            if food['nutrients'].get(key, {}).get('state', 'unknown') == 'unknown']


def candidates(user_id, key, query):
    original = personal(user_id, key)
    gaps = missing(original)
    hits = [hit for hit in catalog.search(user_id, query, limit=12) if hit['scope'] == 'catalog']
    foods = catalog.details(user_id, [{'ref': hit['ref']} for hit in hits])
    return {'original': original, 'missing': gaps, 'candidates': [
        {'food': food, 'available': [nutrient for nutrient in gaps
                                    if food['nutrients'].get(nutrient, {}).get('state') == 'known']}
        for food in foods]}


def comparison(user_id, key, candidate_ref, amount, unit, target):
    original = personal(user_id, key)
    if not str(candidate_ref).startswith('catalog:'):
        raise NutritionError('Selecciona una identidad publicada del catálogo.')
    candidate = catalog.detail(user_id, candidate_ref)
    original_part = ingredient(original, amount, unit)
    candidate_part = ingredient(candidate, amount, unit)
    claims = {'owner': user_id, 'original': key, 'original_hash': ni.hash_document(original),
              'candidate': candidate_ref, 'candidate_hash': ni.hash_document(candidate),
              'candidate_revision': candidate['revision'], 'amount': original_part['amount'],
              'unit': unit, 'date': target.isoformat()}
    token = URLSafeTimedSerializer(current_app.secret_key, salt='nutrition-equivalent-review-v1').dumps(claims)
    return {'original': original, 'candidate': candidate, 'original_part': original_part,
            'candidate_part': candidate_part, 'missing': missing(original), 'token': token}


def reviewed_selection(user_id, key, token):
    try:
        claims = URLSafeTimedSerializer(current_app.secret_key, salt='nutrition-equivalent-review-v1').loads(token, max_age=1800)
    except BadSignature as error:
        raise NutritionError('La revisión cambió o venció. Compara de nuevo.', 409) from error
    if claims.get('owner') != user_id or claims.get('original') != key:
        raise NutritionError('Revisión no encontrada.', 404)
    ni.enabled()
    ni.lock_owner(user_id)
    original = personal(user_id, key)
    try:
        candidate = catalog.detail(user_id, claims['candidate'])
    except NutritionError as error:
        raise NutritionError('La revisión publicada ya no está activa. Compara de nuevo.', 409) from error
    if ni.hash_document(original) != claims['original_hash'] or ni.hash_document(candidate) != claims['candidate_hash']:
        raise NutritionError('Cambió una definición o revisión de fuente. Compara de nuevo.', 409)
    return claims, candidate


def prepare(user_id, claims, candidate):
    # An explicit choice of the actual catalog identity, not an enrichment or
    # transfer of its nutrients into the original personal definition.
    return ni.create_draft(user_id, target=claims['date'], name=candidate['name'], entries=[{
        'ref': claims['candidate'], 'revision': claims['candidate_revision'],
        'amount': claims['amount'], 'unit': claims['unit']}])
