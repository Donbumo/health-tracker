"""Repeatable synthetic persistence checks on the existing reserved QA schema.

Run mariadb_qa.py first. This runner never migrates, resets or drops tables;
each invocation owns new explicitly fictional users and temporary files.
"""
import copy
from types import SimpleNamespace
from uuid import uuid4

from mariadb_qa import ROOT, application, db, ni, catalog, NutritionError, Decimal, date, json
from sqlalchemy import inspect, text
from app.models import User, DailyNutrition, NutritionItem
from app.models.nutrition_intelligence import MealLog
from app.models.nutrition_intelligence import CatalogFood, FoodCatalogRevision
from flask_migrate import check, upgrade
from app.services.mobile_health import (
    create_food, patch_food, serialize_nutrition_day,
    patch_nutrition_item, delete_nutrition_item, duplicate_nutrition_item,
)
from app.services.account_restore import AccountRestoreService
from app.services.exporters.user_data import build_user_data_document
from app.services.nutrition_portability import export_bundle, semantic_snapshot
from app.services.backups import AccountBackupService, BackupRestoreCoordinator
from app.services.ai.capabilities.domains.nutrition_actions import apply_food
from app.services.ai.tools import _nutrition
from tests.test_full_backup import _stage


def new_user(label):
    owner = User(username='QA synthetic ' + label + ' ' + uuid4().hex, role='user', timezone='UTC')
    owner.set_password('QA fictional password only')
    db.session.add(owner)
    db.session.commit()
    return owner.id


def rejected(operation, status):
    try:
        operation()
    except Exception as error:
        actual = getattr(error, 'status', getattr(error, 'status_code', None))
        assert actual == status
        db.session.rollback()
    else:
        raise AssertionError('Unauthorized/conflicting operation unexpectedly accepted')


def accept_all(owner, draft):
    for index in range(len(draft.snapshot_json['ingredients'])):
        draft = ni.mutate_draft(owner, draft.public_id, draft.revision, 'accept', {'index': index})
    return draft


def snapshots(owner):
    return {row['local_date']: semantic_snapshot(row['snapshot']) for row in export_bundle(owner)['logs']}


def verify(level):
    app = application(level)
    with app.app_context():
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT DATABASE()')).scalar() == 'nutrition_intelligence_qa_20261009'
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar() == '20261009_0044'
            assert connection.execute(text('SELECT @@tx_isolation')).scalar().replace('-', ' ') == level
        owner, other = new_user(level), new_user('other ' + level)
        ref = next(row['ref'] for row in catalog.search(owner, 'QA fictitious food') if row['scope'] == 'catalog')
        product = create_food(owner, {'name': 'QA private iron zero', 'calories_per_100g': '100', 'protein_g_per_100g': '2'})
        product.nutrition_json = {'nutrients': {
            'iron': {'state': 'known', 'value': '0', 'unit': 'mg'},
            'phosphorus': {'state': 'trace', 'value': None, 'unit': 'mg'},
            'zinc': {'state': 'below_limit', 'value': None, 'limit': '1', 'unit': 'mg'},
        }, 'servings': [], 'density_g_ml': None}
        db.session.commit()
        private_ref, product_key = 'user:' + product.public_id, product.public_id
        assert not any(row['ref'] == private_ref for row in catalog.search(other))
        rejected(lambda: catalog.detail(other, private_ref), 404)
        target = '2026-10-24'
        draft = ni.create_draft(owner, target=target, entries=[
            {'ref': private_ref, 'amount': '100', 'unit': 'g'},
            {'ref': ref, 'amount': '100', 'unit': 'g'},
        ])
        draft = accept_all(owner, draft)
        recipe = ni.save_template(owner, draft.public_id, draft.revision)
        draft_key, recipe_key, recipe_revision = draft.public_id, recipe.public_id, recipe.revision
        token = ni.confirmation_token(draft)
        db.session.commit()
        rejected(lambda: ni.owned_draft(other, draft_key), 404)
        rejected(lambda: ni.confirm(other, token), 404)
        rejected(lambda: ni.template_draft(other, recipe_key), 404)
        log, replay = ni.confirm(owner, token)
        assert not replay
        db.session.commit()
        log_key, projection_key = log.public_id, db.session.get(NutritionItem, log.projection_item_id).public_id
        historical = copy.deepcopy(log.snapshot_json)
        assert ni.confirm(owner, token)[1]
        db.session.commit()
        rejected(lambda: ni.owned_log(other, log_key), 404)
        rejected(lambda: ni.repeat(other, log_key), 404)
        assert not ni.daily_summary(other, date.fromisoformat(target))['logs']
        day = ni.daily_summary(owner, date.fromisoformat(target))
        assert day['day'].calories == Decimal('265')
        assert Decimal(day['summary']['energy']['value']) == Decimal('265')
        assert day['summary']['iron']['state'] == 'partial'
        assert Decimal(day['summary']['iron']['value']) == 0
        assert Decimal(day['summary']['iron']['coverage']) == 50
        assert day['summary']['vitamin_c']['state'] == 'unknown'
        assert day['summary']['vitamin_c']['value'] is None
        assert historical['ingredients'][0]['contribution']['phosphorus']['state'] == 'trace'
        assert historical['ingredients'][0]['contribution']['zinc']['state'] == 'below_limit'
        assert historical['ingredients'][0]['contribution']['zinc']['value'] is None
        assert ni.comparison_value(day['day'], 'fiber_g') is None
        legacy = serialize_nutrition_day(owner, date.fromisoformat(target))
        assert Decimal(legacy['totals']['calories_kcal']) == 265
        assert legacy['remaining'] is None
        assert legacy['meals'][0]['items'][0]['snapshot_available']
        assert not legacy['meals'][0]['items'][0]['data_complete']
        for operation, payload in [
            (patch_nutrition_item, {'base_revision': 1, 'name': 'QA forbidden flatten'}),
            (delete_nutrition_item, {'base_revision': 1}),
            (duplicate_nutrition_item, {}),
        ]:
            rejected(lambda op=operation, p=payload: op(owner, projection_key, p), 409)
        patch_food(owner, product_key, {'base_revision': 1, 'calories_per_100g': '200'})
        db.session.commit()
        assert Decimal(catalog.detail(owner, private_ref)['nutrients']['energy']['value']) == 200
        assert ni.owned_log(owner, log_key).snapshot_json == historical
        edit = ni.template_draft(owner, recipe_key, target)
        edit = ni.mutate_draft(owner, edit.public_id, edit.revision, 'amount', {'index': 1, 'amount': '200', 'unit': 'g'})
        edit = accept_all(owner, edit)
        updated = ni.save_template(owner, edit.public_id, edit.revision, recipe_key=recipe_key, base_revision=recipe_revision)
        assert updated.revision == recipe_revision + 1
        db.session.commit()
        assert ni.owned_log(owner, log_key).snapshot_json == historical
        repeated = ni.repeat(owner, log_key, '2026-10-25')
        assert ni.pending(repeated) == 2
        assert repeated.snapshot_json['ingredients'] == historical['ingredients']
        repeated = accept_all(owner, repeated)
        repeated_log, replay = ni.confirm(owner, ni.confirmation_token(repeated))
        assert not replay and repeated_log.public_id != log_key
        assert repeated_log.client_event_id != log.client_event_id
        db.session.commit()
        assert db.session.query(MealLog).filter_by(user_id=owner).count() == 2
        assert ni.daily_summary(owner, date(2026, 10, 25))['day'].calories == Decimal('265')
        # Legacy aggregate needs an explicit, disjoint authority choice.
        db.session.add(DailyNutrition(user_id=owner, date=date(2026, 10, 26), source='qa', calories=500, protein_g=20))
        db.session.commit()
        baseline = ni.create_draft(owner, target='2026-10-26', entries=[{'ref': ref, 'amount': '100', 'unit': 'g'}])
        baseline = accept_all(owner, baseline)
        baseline_token = ni.confirmation_token(baseline)
        db.session.commit()
        rejected(lambda: ni.confirm(owner, baseline_token), 409)
        ni.confirm(owner, baseline_token, authority='disjoint_aggregate')
        db.session.commit()
        preserved = ni.daily_summary(owner, date(2026, 10, 26))
        assert preserved['day'].calories == Decimal('665') and preserved['day'].protein_g == Decimal('51')
        assert Decimal(preserved['day'].authority_baseline_json['original_totals']['calories']) == 500
        # Existing Operator apply handler remains idempotent and legacy compatible.
        action = SimpleNamespace(public_id=str(uuid4()))
        payload = {'date': '2026-10-28', 'meal_type': 'lunch', 'items': [{'name': 'QA Operator item', 'calories_kcal': '12.345', 'protein_g': '3'}]}
        applied = apply_food(db.session.get(User, owner), action, payload, None, None)
        assert applied == apply_food(db.session.get(User, owner), action, payload, None, None)
        db.session.commit()
        assert Decimal(serialize_nutrition_day(owner, date(2026, 10, 28))['totals']['calories_kcal']) == Decimal('12.345')
        app.config['AI_TODAY_OVERRIDE'] = date.fromisoformat(target)
        assert _nutrition(db.session.get(User, owner), {'preset': 'today'}).data['nutrient_details']
        # Full official account export/restore, owner remap and replay.
        expected = snapshots(owner)
        document = build_user_data_document(db.session.get(User, owner), owner)
        recipient = new_user('restore ' + level)
        service = AccountRestoreService()
        preview = service.preview(document, user_id=recipient)
        assert not any(op['operation'] in {'invalid', 'conflict'} for op in preview['plan']['operations'])
        assert service.commit(document, user_id=recipient, confirmation_token=preview['confirmation_token'])['committed']
        assert snapshots(recipient) == expected
        preview = service.preview(document, user_id=recipient)
        assert next(op for op in preview['plan']['operations'] if op['section'] == 'nutrition_intelligence')['operation'] == 'skip'
        assert service.commit(document, user_id=recipient, confirmation_token=preview['confirmation_token'])['committed']
        assert db.session.query(MealLog).filter_by(user_id=recipient).count() == 3
        assert ni.daily_summary(recipient, date(2026, 10, 26))['day'].calories == Decimal('665')
        # ZIP official backup follows the same complete snapshot contract.
        backup = AccountBackupService()
        archive = backup.create(db.session.get(User, owner), user_id=owner)
        archive_path = backup.resolve_download(archive, user_id=owner)
        backup_owner = new_user('backup ' + level)
        coordinator = BackupRestoreCoordinator()
        staging = _stage(archive_path, coordinator, backup_owner)
        preview = coordinator.preview(staging_id=staging, user_id=backup_owner)
        assert coordinator.confirm(staging_id=staging, user_id=backup_owner, confirmation_token=preview['confirmation_token'])['committed']
        assert snapshots(backup_owner) == expected
        app.config['NUTRITION_INTELLIGENCE_ENABLED'] = False
        rejected(lambda: ni.repeat(owner, log_key), 404)
        assert ni.owned_log(owner, log_key).snapshot_json == historical
    return {'level': level, 'checks': {name: 'pass' for name in (
        'effective_isolation', 'owner_only', 'idempotency', 'unknown_vs_zero', 'trace_below_limit', 'partial_micronutrients',
        'no_double_count', 'immutable_food_history', 'immutable_recipe_history', 'repeat_new_event',
        'legacy_macros_authority', 'android_projection_read', 'android_mutation_guard',
        'operator_apply_replay', 'operator_quality_read', 'account_restore_owner_remap_replay',
        'zip_restore_snapshots', 'flag_off_preserves_history',
    )}}


def verify_catalog_and_schema():
    with application('READ COMMITTED').app_context():
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT DATABASE()')).scalar() == 'nutrition_intelligence_qa_20261009'
            inspector = inspect(connection)
            expected = {
                'food_catalog_sources': set(), 'food_catalog_revisions': {'uq_food_catalog_revision'},
                'catalog_foods': {'uq_catalog_food_identity', 'ix_catalog_food_search'},
                'nutrients': set(), 'food_nutrients': {'uq_food_nutrient'},
                'food_servings': {'uq_food_serving'}, 'meal_drafts': {'ix_meal_draft_owner'},
                'meal_logs': {'uq_meal_log_event', 'ix_meal_log_owner_date'},
            }
            for table, names in expected.items():
                assert table in inspector.get_table_names()
                actual = {index['name'] for index in inspector.get_indexes(table)}
                actual |= {index['name'] for index in inspector.get_unique_constraints(table)}
                assert names <= actual
            assert any(foreign['constrained_columns'] == ['projection_item_id'] and foreign['options'].get('ondelete', 'RESTRICT') == 'RESTRICT'
                       for foreign in inspector.get_foreign_keys('meal_logs'))
            permissions = set(connection.execute(text("SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES WHERE TABLE_SCHEMA='nutrition\\\\_intelligence\\\\_qa\\\\_20261009'")).scalars())
            assert permissions == {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'INDEX', 'REFERENCES'}
            assert set(connection.execute(text("SELECT PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES")).scalars()) <= {'USAGE'}
            legacy = connection.execute(text("SELECT calories FROM daily_nutrition JOIN users ON users.id=daily_nutrition.user_id WHERE username='QA legacy migration'")).scalar_one()
            assert legacy == Decimal('1234.567')
        source = json.loads((ROOT / 'examples/qa/nutrition-intelligence/catalog-sample.json').read_text(encoding='utf-8'))
        staged = catalog.stage(source)
        state = next(row for row in catalog.status() if row['source'] == source['source'])
        if state['active'] != source['revision']:
            catalog.activate(source['source'], source['revision'], state['revision'])
        db.session.commit()
        count = db.session.execute(db.select(db.func.count()).select_from(CatalogFood).join(FoodCatalogRevision)
            .where(FoodCatalogRevision.source_id == source['source'], FoodCatalogRevision.revision == source['revision'])).scalar_one()
        assert count == 37
        digest = staged.sha256
        assert digest == 'b1b96afe3d58c12c438532d538383a1f4ace4ec6947378ad78f4762bdbf87bd9'
        upgrade(directory=str(ROOT / 'backend/migrations'), revision='head')
        check(directory=str(ROOT / 'backend/migrations'))
        return {'tables_indexes_foreign_keys': 'pass', 'schema_local_privileges_only': 'pass',
                'legacy_migration_fixture_preserved': 'pass', 'repeated_upgrade_after_consumption': 'pass', 'db_check': 'pass',
                'catalog': {'source': source['source'], 'revision': source['revision'], 'foods': count, 'sha256': digest}}


if __name__ == '__main__':
    try:
        report = {'data': 'synthetic QA only', 'isolations': [verify(level) for level in ('READ COMMITTED', 'REPEATABLE READ')]}
        report['schema_catalog'] = verify_catalog_and_schema()
        (ROOT / 'design/nutrition-intelligence-2/production-qa/mariadb-persistence-results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report))
    except Exception as error:
        # Never print payloads, SQL parameters, connection credentials or files.
        import traceback
        print('MariaDB persistence gate failed: ' + type(error).__name__)
        for frame in traceback.extract_tb(error.__traceback__):
            if 'nutrition' in frame.filename:
                print(f'{frame.name}:{frame.lineno}')
        raise SystemExit(1)
