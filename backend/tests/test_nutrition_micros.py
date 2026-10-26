"""Nutrition 3 A: synthetic SQLite fixtures, no private files or databases."""
import copy
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import DailyNutrition, FoodProduct, NutritionItem, NutritionMeal, User
from app.services import food_catalog as catalog, nutrition_intelligence as ni
from app.services.nutrition_math import NUTRIENTS
from app.services.nutrition_micros import overview
from tests.conftest import login


TARGET = date(2026, 10, 26)


@pytest.fixture
def micros(app, user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED'] = True
    food = {'source': 'qa_micros', 'source_food_id': 'QA_ONLY', 'revision': '1',
            'name': 'QA fictional complete food', 'preparation': 'QA cooked',
            'basis_amount': '100', 'basis_unit': 'g', 'density_g_ml': None, 'servings': [],
            'nutrients': {key: {'state': 'known', 'value': '1', 'unit': definition[1]}
                          for key, definition in NUTRIENTS.items()}}
    food['nutrients']['iron']['value'] = '5'
    food['nutrients']['vitamin_d']['value'] = '0'
    special = copy.deepcopy(food)
    special.update(source_food_id='QA_TRACE', name='QA fictional trace food')
    special['nutrients']['iron'] = {'state': 'below_limit', 'limit': '0.1', 'value': None, 'unit': 'mg'}
    special['nutrients']['vitamin_d'] = {'state': 'trace', 'value': None, 'unit': 'ug'}
    catalog.stage({'schema_version': '2.0', 'source': 'qa_micros', 'revision': '1',
                   'license': 'QA synthetic only', 'foods': [food, special]})
    catalog.activate('qa_micros', '1', 1)
    missing = FoodProduct(user_id=user, name='QA fictional unknown personal food', source='manual')
    db.session.add(missing); db.session.commit()
    hits = catalog.search(user, source='qa_micros')
    return {'complete': next(h['ref'] for h in hits if h['source_food_id'] == 'QA_ONLY'),
            'special': next(h['ref'] for h in hits if h['source_food_id'] == 'QA_TRACE'),
            'missing': 'user:' + missing.public_id, 'food': food}


def consume(user, refs, target=TARGET, save=False, authority=None, declaration=None, amount='100', unit='g'):
    draft = ni.create_draft(user, target=target.isoformat(), name='QA fictional consumed meal',
                            entries=[{'ref': ref, 'amount': amount, 'unit': unit} for ref in refs])
    if declaration:
        doc = copy.deepcopy(draft.snapshot_json)
        doc.update(declared_nutrition={'confirmed': True, 'basis_amount': '1', 'basis_unit': 'portion',
                                       'nutrients': declaration}, composition={'complete': False})
        draft.snapshot_json = doc
    for index in range(len(refs)):
        ni.mutate_draft(user, draft.public_id, draft.revision, 'accept', {'index': index})
    recipe = ni.save_template(user, draft.public_id, draft.revision) if save else None
    log, _ = ni.confirm(user, ni.confirmation_token(draft), authority=authority)
    db.session.commit()
    return log, recipe


def test_complete_partial_zero_and_daily_parity(app, user, micros):
    consume(user, [micros['complete']])
    view = overview(user, TARGET, 7, 'vitamin_d')
    assert view['summary'] == ni.daily_summary(user, TARGET)['summary']
    assert Decimal(view['summary']['iron']['value']) == 5
    assert view['summary']['iron']['coverage'] == '100'
    assert view['chart']['valid_days'] == 1 and view['chart']['average'] == 0
    consume(user, [micros['missing']])
    view = overview(user, TARGET, 7)
    assert Decimal(view['summary']['iron']['value']) == 5
    assert view['summary']['iron']['state'] == 'partial'
    assert Decimal(view['summary']['iron']['coverage']) == 50
    assert view['chart']['valid_days'] == 0 and view['chart']['partial_average'] == 5
    assert db.session.query(NutritionItem).count() == 2  # no second contribution from projections


def test_trace_limit_exact_zero_are_independent(app, client, user, micros):
    log, _ = consume(user, [micros['special']])
    login(client)
    html = client.get('/nutrition/micronutrients?date=2026-10-26&nutrient=iron').get_data(as_text=True)
    assert '&lt; 0.1 mg' in html and 'Bajo el límite' in html
    assert 'No hay cantidades exactas para graficar' in html and '<circle' not in html
    detail = client.get('/nutrition/logs/' + log.public_id).get_data(as_text=True)
    assert 'Traza · sin cantidad exacta' in detail and '&lt; 0.1 mg' in detail
    assert log.snapshot_json['ingredients'][0]['contribution']['iron']['value'] is None
    consume(user, [micros['complete']])
    view = overview(user, TARGET, 7, 'vitamin_d')
    assert Decimal(view['summary']['vitamin_d']['value']) == 0
    assert view['summary']['vitamin_d']['state'] == 'partial'
    assert view['qualifiers']['vitamin_d']['trace'] == 1


def test_declared_totals_never_sum_composition_again(app, client, user, micros):
    log, _ = consume(user, [micros['complete']], declaration={
        'iron': {'state': 'known', 'value': '8', 'unit': 'mg'},
        'vitamin_d': {'state': 'trace', 'value': None, 'unit': 'ug'}})
    view = overview(user, TARGET, 7)
    assert Decimal(view['summary']['iron']['value']) == 8
    assert Decimal(log.snapshot_json['composition_summary']['iron']['value']) == 5
    login(client)
    html = client.get('/nutrition/logs/' + log.public_id).get_data(as_text=True)
    assert '8 mg' in html and '5 mg' in html and 'Traza · sin cantidad exacta' in html
    assert 'Composición estimada · no sumar a la declaración' in html


@pytest.mark.parametrize('authority', [None, 'derive_items', 'disjoint_aggregate'])
def test_legacy_authority_and_disjoint_aggregates(app, user, micros, authority):
    day = DailyNutrition(user_id=user, date=TARGET, source='qa', calories=1000, sodium_mg=100)
    db.session.add(day); db.session.flush()
    meal = NutritionMeal(user_id=user, daily_nutrition_id=day.id, name='QA legacy meal',
                         meal_type='lunch', sort_order=1)
    db.session.add(meal); db.session.flush()
    db.session.add(NutritionItem(user_id=user, nutrition_meal_id=meal.id, name='QA legacy item',
                                 sort_order=1, source='qa', calories=300, sodium_mg=20))
    db.session.commit()
    if authority:
        consume(user, [micros['complete']], authority=authority)
    view = overview(user, TARGET)
    assert view['summary'] == ni.daily_summary(user, TARGET)['summary']
    assert len(view['legacy']) == 1
    if authority == 'disjoint_aggregate':
        assert Decimal(view['summary']['energy']['value']) == 1001
        assert view['summary']['iron']['state'] == 'partial'
        assert not view['legacy'][0]['included']
    elif authority == 'derive_items':
        assert Decimal(view['summary']['energy']['value']) == 301
        assert view['legacy'][0]['included']
    else:
        assert Decimal(view['summary']['energy']['value']) == 1000
        assert view['summary']['iron']['value'] is None
    assert view['summary']['iron']['coverage'] is None


def test_legacy_without_ingredients_and_empty_day(app, user, micros):
    db.session.add(DailyNutrition(user_id=user, date=TARGET, source='qa', calories=0))
    db.session.commit()
    view = overview(user, TARGET, 30, 'energy')
    assert Decimal(view['summary']['energy']['value']) == 0
    assert view['summary']['energy']['state'] == 'partial'
    assert view['summary']['vitamin_c']['value'] is None
    assert not view['logs'] and not view['legacy']
    empty = overview(user, TARGET + timedelta(days=1), 30)
    assert empty['summary']['iron']['value'] is None


@pytest.mark.parametrize('period', [7, 30, 90])
def test_period_boundaries_means_gaps_and_denominators(app, user, micros, period):
    consume(user, [micros['complete']], TARGET - timedelta(days=period))  # outside
    consume(user, [micros['complete']], TARGET - timedelta(days=period - 1))
    consume(user, [micros['complete'], micros['missing']], TARGET - timedelta(days=1))
    consume(user, [micros['special']], TARGET)
    view = overview(user, TARGET, period)
    chart = view['chart']
    assert len(chart['samples']) == period
    assert chart['valid_days'] == chart['partial_days'] == 1
    assert chart['average'] == chart['partial_average'] == 5
    assert chart['unknown_days'] == period - 2
    assert chart['samples'][-1]['value'] is None
    assert len(chart['paths']) == 1  # partial/unknown samples cannot connect a complete line


def test_snapshot_immutable_after_recipe_and_food_edits(app, client, user, micros):
    log, recipe = consume(user, [micros['complete'], micros['missing']], save=True)
    frozen = copy.deepcopy(log.snapshot_json)
    recipe.nutrition_snapshot_json = None; recipe.revision += 1
    product = db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id == user)).scalar_one()
    product.name = 'QA changed current definition'
    product.nutrition_json = {'nutrients': {'iron': {'state': 'known', 'value': '999', 'unit': 'mg'}}}
    product.revision += 1; db.session.commit()
    assert overview(user, TARGET)['summary']['iron']['value'] == frozen['summary']['iron']['value']
    login(client)
    html = client.get('/nutrition/logs/' + log.public_id).get_data(as_text=True)
    assert 'QA fictional unknown personal food' in html and '999 mg' not in html
    assert f'/recipes/{recipe.id}' in html
    assert log.snapshot_json == frozen


def test_owner_isolation_get_no_dml_and_disabled_reads(app, client, user, micros):
    log, recipe = consume(user, [micros['complete'], micros['missing']], save=True)
    other = User(username='QA other micros owner', role='user', timezone='Pacific/Kiritimati')
    other.set_password('QA fictional only')
    db.session.add(other); db.session.commit()
    assert overview(other.id, TARGET)['summary']['iron']['value'] is None
    with client.session_transaction() as session:
        session['_user_id'] = str(other.id); session['_fresh'] = True
    assert client.get('/nutrition/logs/' + log.public_id).status_code == 404
    assert client.get('/nutrition/foods/' + micros['missing']).status_code == 404
    assert client.get(f'/recipes/{recipe.id}').status_code == 404
    with client.session_transaction() as session:
        session['_user_id'] = str(user); session['_fresh'] = True
    from flask import g
    g.pop('_login_user', None)
    app.config['NUTRITION_INTELLIGENCE_ENABLED'] = False
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(db.engine, 'before_cursor_execute', capture)
    try:
        for path in ['/nutrition/micronutrients?date=2026-10-26&user_id=' + str(other.id),
                     '/nutrition/logs/' + log.public_id]:
            response = client.get(path)
            assert response.status_code == 200
            assert 'QA fictional consumed meal' in response.get_data(as_text=True)
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture)
    assert not set(statements) & {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}


def test_timezone_effective_session_date_validation_and_compatibility(app, client, user, micros, monkeypatch):
    from app.nutrition import routes
    from datetime import datetime, timezone
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(routes, 'datetime', FixedDatetime)
    db.session.get(User, user).timezone = 'America/Mexico_City'; db.session.commit()
    consume(user, [micros['complete']])
    login(client)
    assert '2026-10-26 · Macros' in client.get('/nutrition/micronutrients').get_data(as_text=True)
    assert client.get('/nutrition/micronutrients?date=bad').status_code == 422
    assert client.get('/nutrition/micronutrients?date=0001-01-01').status_code == 422
    assert client.get('/nutrition/micronutrients?date=9999-12-31').status_code == 422
    for query in ['period=abc', 'period=0&nutrient=bad', 'period=90&nutrient=folate_dfe']:
        assert client.get('/nutrition/micronutrients?date=2026-10-26&' + query).status_code == 200
    for path in ['/nutrition/?date=2026-10-26', '/dashboard', '/daily-energy', '/ai']:
        assert client.get(path).status_code == 200


def test_volume_without_density_and_scaled_limit(app, client, user, micros):
    product = FoodProduct(user_id=user, name='QA fictional volume', source='manual',
                          nutrition_json={'basis_amount': '100', 'basis_unit': 'ml',
                                          'nutrients': {'iron': {'state': 'known', 'value': '2', 'unit': 'mg'}}})
    db.session.add(product); db.session.commit()
    consume(user, ['user:' + product.public_id], amount='150', unit='ml')
    view = overview(user, TARGET)
    assert Decimal(view['summary']['iron']['value']) == 3
    assert view['summary']['iron']['coverage'] is None
    log, _ = consume(user, [micros['special']], amount='30')
    login(client)
    assert '&lt; 0.03 mg' in client.get('/nutrition/logs/' + log.public_id).get_data(as_text=True)


def test_archived_catalog_revision_and_period_snapshot_parity(app, client, user, micros):
    log, _ = consume(user, [micros['complete']])
    frozen = copy.deepcopy(log.snapshot_json)
    updated = copy.deepcopy(micros['food']); updated['revision'] = '2'
    updated['nutrients']['iron']['value'] = '999'
    catalog.stage({'schema_version': '2.0', 'source': 'qa_micros', 'revision': '2',
                   'license': 'QA synthetic only', 'foods': [updated]})
    catalog.activate('qa_micros', '2', 2); db.session.commit()
    view = overview(user, TARGET + timedelta(days=1), 7)
    assert view['chart']['samples'][-2]['value'] == frozen['summary']['iron']['value']
    login(client)
    response = client.get('/nutrition/foods/' + micros['complete'] + '?revision=1')
    assert response.status_code == 200 and '999' not in response.get_data(as_text=True)
    assert client.get('/nutrition/foods/' + micros['complete']).status_code == 404


def test_imported_daily_declaration_and_later_disjoint_meal(app, user, micros):
    import json
    from app.services import nutrition_import as imports
    from app.services.importers.standard_import_executor import StandardImportExecutor
    source = {'schema_version': '1.0', 'record_type': 'daily_nutrition', 'user_id': user,
              'source_type': 'uploaded', 'data': {'date': TARGET.isoformat(), 'calories_kcal': 450}}
    row = imports.start(user, json.dumps(source).encode(), 'QA fictional aggregate.json')
    review = copy.deepcopy(row.review_json); review['destination'] = 'daily_aggregate'
    review['rows'][0].update(confirmed=True, basis_amount='1', basis_unit='portion')
    review['rows'][0]['declaration']['iron'] = {'state': 'known', 'value': '2.1', 'unit': 'mg'}
    row.review_json = review; db.session.commit()
    result = StandardImportExecutor().commit_documents([imports.canonical(row)], user_id=user,
                                                       target_type='nutrition_import', confirmed=True)
    assert result['committed']
    view = overview(user, TARGET)
    assert Decimal(view['summary']['iron']['value']) == Decimal('2.1')
    assert view['chart']['average'] == Decimal('2.1')
    assert not view['logs']
    consume(user, [micros['complete']], authority='disjoint_aggregate')
    view = overview(user, TARGET)
    assert Decimal(view['summary']['iron']['value']) == Decimal('7.1')
    assert view['summary']['iron']['coverage'] is None
