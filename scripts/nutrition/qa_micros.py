"""Nutrition 3 A QA. Only public catalog artifacts and fictional accounts.

SQLite is temporary by default. Optional MariaDB URI must target our dedicated
loopback QA schema. Never reads .env or the application's configured database.
"""
import argparse
from collections import Counter
import copy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import event, text
from flask_migrate import upgrade, check, stamp
from app import create_app
from app.extensions import db
from app.models import DailyNutrition, User
from app.services import food_catalog as catalog
from app.services.nutrition_math import NUTRIENTS
from app.services.nutrition_micros import overview
from tests.test_nutrition_micros import micros, consume, TARGET

OUT = ROOT / 'design/nutrition-intelligence-3-a/qa'
QA_URI = ('mysql+pymysql://nutrition_micros_qa:QA-fictional-micros-only'
          '@127.0.0.1:33383/nutrition_micros_qa?charset=utf8mb4')


def audit_catalog():
    """Public catalog only. Never joins FoodProduct or any owner table."""
    foods = db.session.execute(catalog.catalog_query()).scalars().all()
    keys = list(NUTRIENTS)
    sources, inventory = {}, []
    for row in foods:
        doc = row.snapshot_json
        source = doc['source']
        if source not in sources:
            sources[source] = {'revision': row.catalog_revision.revision, 'foods': 0,
                               'nutrients': {key: Counter() for key in keys}, 'basis': Counter()}
        report = sources[source]; report['foods'] += 1
        report['basis'][doc['basis_unit']] += 1
        states = []
        for key in keys:
            nutrient = doc['nutrients'].get(key)
            state = nutrient['state'] if nutrient else 'absent'
            report['nutrients'][key][state] += 1
            if nutrient and nutrient['state'] == 'known' and nutrient['value'] is not None and Decimal(nutrient['value']) == 0:
                report['nutrients'][key]['known_zero'] += 1
            states.append({'known': 'K', 'unknown': 'U', 'trace': 'T', 'below_limit': 'L', 'absent': '-'}[state])
        inventory.append([source, doc['source_food_id'], doc['revision'], doc['basis_amount'], doc['basis_unit'],
                          doc.get('density_g_ml') is not None or doc['basis_unit'] == 'g', ''.join(states)])
    (OUT / 'catalog-inventory.json').write_text(json.dumps({
        'scope': 'Public repository catalogs activated in isolated QA; no production inventory claim',
        'state_legend': {'K': 'known', 'U': 'unknown', 'T': 'trace', 'L': 'below_limit', '-': 'absent'},
        'nutrient_order': keys, 'units': {key: definition[1] for key, definition in NUTRIENTS.items()},
        'columns': ['source', 'source_food_id', 'food_revision', 'basis_amount', 'basis_unit', 'mass_calculable', 'states'],
        'foods': inventory}, separators=(',', ':'), ensure_ascii=False) + '\n', encoding='utf-8')
    report = {'scope': 'Public artifacts activated in ephemeral QA, before synthetic catalog fixtures',
              'foods': len(foods), 'sources': sources, 'coverage': 'Counts of data availability per identity, not dietary coverage'}
    (OUT / 'catalog-audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return len(foods)


def run(mariadb=False, serve=False):
    OUT.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='ht-ni3-micros-qa-'))
    app = create_app({'TESTING': True, 'SECRET_KEY': 'fictional-micros-ui-qa-secret-only-30a',
                     'API_TOKEN_SIGNING_KEY': 'fictional-micros-api-key-only-30a-qa',
                     'SQLALCHEMY_DATABASE_URI': QA_URI if mariadb else 'sqlite:///' + (temporary / 'qa.sqlite').as_posix(),
                     'SQLALCHEMY_ENGINE_OPTIONS': {}, 'DATA_ROOT': temporary,
                     'UPLOAD_ROOT': temporary / 'raw', 'GENERATED_UPLOAD_ROOT': temporary / 'generated',
                     'PORTABILITY_ROOT': temporary / 'portable', 'SCHEMA_ROOT': ROOT / 'schemas',
                     'NUTRITION_INTELLIGENCE_ENABLED': True, 'NUTRITION_QA_LABEL': True,
                     'AI_ENABLED': False, 'NUTRITION_EXTERNAL_LOOKUP_ENABLED': False})
    with app.app_context():
        if mariadb:
            assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'nutrition_micros_qa'
            assert db.session.execute(text('SELECT CURRENT_USER()')).scalar().startswith('nutrition_micros_qa@')
            db.session.rollback()
        if mariadb:
            upgrade(directory=str(ROOT / 'backend/migrations'))
        else:
            # Existing early FK migrations require MariaDB. SQLite exercises
            # current metadata, like the focal pytest fixtures.
            db.create_all()
            stamp(directory=str(ROOT / 'backend/migrations'))
        check(directory=str(ROOT / 'backend/migrations'))
        owner = User(username='micros-qa', role='user', display_name='QA ficticia', timezone='America/Mexico_City')
        owner.set_password('fictional-micros-qa-password')
        db.session.add(owner); db.session.commit()
        for path in sorted((ROOT / 'examples/catalog/nutrition-2-1').glob('*.json')):
            if path.name == 'manifest.json':
                continue
            doc = json.loads(path.read_bytes())
            catalog.stage(doc); catalog.activate(doc['source'], doc['revision'], 1); db.session.commit()
        count = audit_catalog()
        refs = micros.__wrapped__(app, owner.id)
        log, recipe = consume(owner.id, [refs['complete']], save=True)
        frozen = copy.deepcopy(log.snapshot_json)
        consume(owner.id, [refs['complete'], refs['missing']], TARGET - timedelta(days=1))
        consume(owner.id, [refs['special']], TARGET - timedelta(days=2))
        db.session.add(DailyNutrition(user_id=owner.id, date=TARGET - timedelta(days=4), source='qa', calories=1000))
        db.session.commit()
        for offset in range(5, 90):
            if offset % 5:
                consume(owner.id, [refs['complete']] if offset % 3 else [refs['complete'], refs['missing']],
                        TARGET - timedelta(days=offset), amount=str(60 + (offset % 9) * 15))
        recipe.revision += 1; recipe.nutrition_snapshot_json = None; db.session.commit()
        assert log.snapshot_json == frozen
        statements = []
        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(db.engine, 'before_cursor_execute', capture)
        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = str(owner.id); session['_fresh'] = True
        statuses = {}
        try:
            for path in ['/nutrition/micronutrients?date=2026-10-26&period=90', '/nutrition/logs/' + log.public_id,
                         '/nutrition/?date=2026-10-26', '/dashboard', '/daily-energy']:
                statuses[path.split('?')[0]] = client.get(path).status_code
            assert all(status == 200 for status in statuses.values()), statuses
        finally:
            event.remove(db.engine, 'before_cursor_execute', capture)
        assert not set(statements) & {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}
        views = {period: overview(owner.id, TARGET, period) for period in (7, 30, 90)}
        report = {'data': 'QA synthetic owners and public catalog only', 'engine': db.engine.dialect.name,
                  'catalog_foods': count, 'migration_check': 'pass; MariaDB upgrade' if mariadb else 'pass; SQLite metadata created and stamped, not migration replay',
                  'head': db.session.execute(text('SELECT version_num FROM alembic_version')).scalar(),
                  'get_statuses': statuses, 'get_dml': 0, 'snapshot_after_recipe_edit': 'unchanged',
                  'series': [{'date': sample['date'].isoformat(),
                              **{key: sample[key] for key in ('value','state','unit','coverage')}}
                             for sample in views[90]['chart']['samples']],
                  'periods': {period: {'days': len(view['chart']['samples']), 'valid_days': view['chart']['valid_days'],
                                      'partial_days': view['chart']['partial_days'], 'unknown_days': view['chart']['unknown_days'],
                                      'average': str(view['chart']['average']) if view['chart']['average'] is not None else None,
                                      'partial_average': str(view['chart']['partial_average']) if view['chart']['partial_average'] is not None else None}
                              for period, view in views.items()}}
        for period in (7, 30):
            assert views[period]['chart']['samples'] == views[90]['chart']['samples'][-period:] or all(
                a['value'] == b['value'] and a['state'] == b['state'] for a, b in zip(
                    views[period]['chart']['samples'], views[90]['chart']['samples'][-period:], strict=True))
        (OUT / ('mariadb-report.json' if mariadb else 'sqlite-report.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if not mariadb:
            (OUT / 'qa-state.json').write_text(json.dumps({'username': owner.username, 'log': log.public_id,
                                                         'data': 'QA fictional only'}, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key != 'series'}), flush=True)
    if serve:
        app.run(host='127.0.0.1', port=8031, debug=False, use_reloader=False, load_dotenv=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mariadb', action='store_true')
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    run(args.mariadb, args.serve)
