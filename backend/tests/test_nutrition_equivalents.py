"""Fictional-only B review: proposals never enrich a canonical definition."""
import copy
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import DailyNutrition, FoodProduct, MealDraft, MealLog, User
from app.services import nutrition_equivalents as service, nutrition_intelligence as ni, food_catalog as catalog
from app.services.nutrition_math import NutritionError
from tests.conftest import login
from tests.test_nutrition_micros import micros, consume, TARGET


@pytest.fixture
def reviewed(app, user, micros):
    key = micros['missing'][5:]
    comparison = service.comparison(user, key, micros['complete'], '150', 'g', TARGET)
    return key, comparison


def test_proposals_local_sources_gaps_and_read_only(app, client, user, micros):
    key = micros['missing'][5:]
    product = db.session.scalar(db.select(FoodProduct).where(FoodProduct.public_id == key))
    product.nutrition_json = {'nutrients': {
        'vitamin_d': {'state': 'known', 'value': '0', 'unit': 'ug'},
        'iron': {'state': 'trace', 'value': None, 'unit': 'mg'}}}
    db.session.commit()
    before = copy.deepcopy(product.nutrition_json)
    proposals = service.candidates(user, key, 'QA')
    assert 'vitamin_d' not in proposals['missing'] and 'iron' not in proposals['missing']
    assert proposals['candidates'] and all(p['food']['scope'] == 'catalog' for p in proposals['candidates'])
    assert all(p['food']['revision'] == '1' and p['food']['catalog_revision'] == '1' for p in proposals['candidates'])
    login(client)
    statements = []
    def guard(conn, cursor, stmt, params, context, many):
        statements.append(stmt.lstrip().split()[0].upper())
    event.listen(db.engine, 'before_cursor_execute', guard)
    try:
        response = client.get(f'/nutrition/my-food/{key}/equivalents?q=QA&candidate={micros["complete"]}&amount=150&unit=g')
        assert response.status_code == 200 and response.headers['Cache-Control'] == 'private, no-store'
        assert 'Propuestas para revisar'.upper() in response.text
        assert '7.5 mg' in response.text and 'Traza' in response.text and '0 ug' in response.text
        assert 'ni se envían datos fuera' in response.text
        assert not set(statements) & {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}
    finally:
        event.remove(db.engine, 'before_cursor_execute', guard)
    assert product.nutrition_json == before and not db.session.query(MealDraft).count()


def test_no_candidates_and_explicit_quantity(app, client, user, micros):
    key = micros['missing'][5:]
    assert service.candidates(user, key, 'QA-NO-SUCH-IDENTITY')['candidates'] == []
    for quantity in (None, '0', '-1', 'NaN', 'not-a-number'):
        with pytest.raises(NutritionError):
            service.comparison(user, key, micros['complete'], quantity, 'g', TARGET)
    with pytest.raises(NutritionError):
        service.comparison(user, key, micros['missing'], '100', 'g', TARGET)
    with pytest.raises(NutritionError):
        service.comparison(user, key, micros['complete'], '100', 'ml', TARGET)


def test_qualified_source_values_preserved(app, user, micros):
    comparison = service.comparison(user, micros['missing'][5:], micros['special'], '30', 'g', TARGET)
    vector = comparison['candidate_part']['contribution']
    assert vector['iron']['value'] is None and Decimal(vector['iron']['limit']) == Decimal('0.03')
    assert vector['vitamin_d']['state'] == 'trace'
    assert comparison['original_part']['contribution']['vitamin_d']['state'] == 'unknown'


def test_explicit_selection_only_pending_draft_sequential_replay(app, client, user, micros, reviewed):
    key, comparison = reviewed
    log, recipe = consume(user, [micros['missing']], save=True)
    frozen = copy.deepcopy(log.snapshot_json)
    product = db.session.scalar(db.select(FoodProduct).where(FoodProduct.public_id == key))
    original = (product.revision, copy.deepcopy(product.nutrition_json), product.updated_at)
    login(client)
    path = f'/nutrition/my-food/{key}/equivalents/prepare'
    assert client.post(path, data={'token': comparison['token']}).status_code == 422
    before = db.session.query(MealDraft).count()
    response = client.post(path, data={'token': comparison['token'], 'confirm_identity': 'yes',
                                      'amount': '999', 'unit': 'ml', 'user_id': '999', 'iron': '999'})
    assert response.status_code == 302 and '/nutrition/drafts/' in response.location
    draft_key = response.location.rsplit('/', 1)[1]
    draft = ni.owned_draft(user, draft_key)
    assert draft.state == 'pending' and ni.pending(draft) == 1
    assert draft.snapshot_json['ingredients'][0]['food']['ref'] == micros['complete']
    assert Decimal(draft.snapshot_json['ingredients'][0]['amount']) == 150
    assert db.session.query(MealDraft).count() == before + 1
    assert client.post(path, data={'token': comparison['token'], 'confirm_identity': 'yes'}).location == response.location
    assert db.session.query(MealDraft).count() == before + 1
    assert db.session.query(MealLog).count() == 1 and db.session.query(DailyNutrition).count() == 1
    assert log.snapshot_json == frozen
    assert (product.revision, product.nutrition_json, product.updated_at) == original
    assert recipe.nutrition_snapshot_json['ingredients'][0]['food']['ref'] == micros['missing']


def test_tamper_owner_and_definition_revision(app, user, micros, reviewed):
    key, comparison = reviewed
    with pytest.raises(NutritionError):
        service.reviewed_selection(user, key, comparison['token'] + 'tampered')
    other = User(username='QA equivalent other owner', role='user');other.set_password('QA fictional')
    db.session.add(other);db.session.commit()
    with pytest.raises(NutritionError) as error:
        service.reviewed_selection(other.id, key, comparison['token'])
    assert error.value.status == 404
    with pytest.raises(NutritionError) as error:
        service.personal(other.id, key)
    assert error.value.status == 404
    product = db.session.scalar(db.select(FoodProduct).where(FoodProduct.public_id == key))
    product.revision += 1;db.session.commit()
    with pytest.raises(NutritionError) as error:
        service.reviewed_selection(user, key, comparison['token'])
    assert error.value.status == 409 and db.session.query(MealDraft).count() == 0


def test_source_revision_change_rejected(app, user, micros, reviewed):
    key, comparison = reviewed
    food = copy.deepcopy(micros['food']);food['revision'] = '2'
    food['nutrients']['iron']['value'] = '999'
    catalog.stage({'schema_version': '2.0', 'source': 'qa_micros', 'revision': '2', 'license': 'QA synthetic only', 'foods': [food]})
    catalog.activate('qa_micros', '2', 2);db.session.commit()
    with pytest.raises(NutritionError):
        service.reviewed_selection(user, key, comparison['token'])
    assert db.session.query(MealDraft).count() == 0


def test_web_owner_and_mismatched_review_path(app, client, user, micros, reviewed):
    from flask import g
    key, comparison = reviewed
    other = User(username='QA second equivalents account', role='user');other.set_password('QA fictional only')
    db.session.add(other);db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(other.id);session['_fresh'] = True
    g.pop('_login_user', None)
    assert client.get(f'/nutrition/my-food/{key}/equivalents?user_id={user}').status_code == 404
    assert client.post(f'/nutrition/my-food/{key}/equivalents/prepare',
                       data={'token': comparison['token'], 'confirm_identity': 'yes'}).status_code == 404
    with pytest.raises(NutritionError) as error:
        service.reviewed_selection(user, 'different-original', comparison['token'])
    assert error.value.status == 404 and db.session.query(MealDraft).count() == 0


def test_expiry_flag_csrf_and_no_store(app, client, user, micros, reviewed, monkeypatch):
    key, comparison = reviewed
    from itsdangerous import TimestampSigner
    moment = TimestampSigner.get_timestamp(None)
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: moment + 1801)
    with pytest.raises(NutritionError) as error:
        service.reviewed_selection(user, key, comparison['token'])
    assert error.value.status == 409
    monkeypatch.undo()
    login(client)
    app.config['NUTRITION_INTELLIGENCE_ENABLED'] = False
    path = f'/nutrition/my-food/{key}/equivalents'
    response = client.get(path + '?q=QA')
    assert response.status_code == 200
    assert client.post(path + '/prepare', data={'token': comparison['token'], 'confirm_identity': 'yes'}).status_code == 404
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post(path + '/prepare', data={'token': comparison['token'], 'confirm_identity': 'yes'}).status_code == 400
    assert db.session.query(MealDraft).count() == 0
    assert client.get('/nutrition/micronutrients').headers['Cache-Control'] == 'private, no-store'
    assert client.get('/nutrition/logs/QA-no-log').headers['Cache-Control'] == 'private, no-store'
